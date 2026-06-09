import re
import gitlab


class WikiMixin:

    def upload_to_wiki(self, group, page_title, content):
        # Save a local copy when running inside _run_reports
        wiki_dir = getattr(self, '_wiki_save_dir', None)
        if wiki_dir is not None:
            safe = re.sub(r'[^a-z0-9\-]', '-',
                          page_title.lower().replace('/', '--').replace(' ', '-'))
            safe = re.sub(r'-+', '-', safe).strip('-')
            wiki_dir.mkdir(parents=True, exist_ok=True)
            (wiki_dir / f"{safe}.md").write_text(content, encoding="utf-8")

        try:
            import re as _re
            # Compute slug to match GitLab's generation:
            #   - non-ASCII preserved (em-dash, ×, →, etc.)
            #   - & preserved (GitLab keeps it; confirmed from live slugs)
            #   - other non-alnum ASCII → space
            #   - spaces → dashes, consecutive dashes collapsed
            # Title-based lookup cannot be used because GitLab stores only the
            # leaf segment as the title for nested-path pages, so the lookup
            # key would never match the full path we pass in.
            _s = _re.sub(r'[^\x80-\U0010FFFFa-zA-Z0-9/\-& ]', ' ', page_title)
            _s = _re.sub(r' +', ' ', _s).strip()
            _s = _s.replace(' ', '-')
            _s = _re.sub(r'-+', '-', _s)
            page_slug = _s.strip('-')

            # Cache is keyed {group_id: {slug: page_object}}.
            # Built from wikis.list() so it uses actual GitLab slugs (no
            # URL-encoding of slashes, unlike wikis.get()).
            # Non-root groups are loaded lazily on first access.
            cache = getattr(self, '_wiki_page_cache', None)
            page  = None
            if cache is not None:
                gid   = group.id
                _lock = getattr(self, '_wiki_cache_lock', None)
                if gid not in cache:
                    # Fetch outside the lock — API call can take seconds.
                    try:
                        loaded = {p.slug: p for p in group.wikis.list(all=True)}
                    except Exception:
                        loaded = {}
                    # Double-checked: only write if another thread hasn't already.
                    if _lock:
                        with _lock:
                            if gid not in cache:
                                cache[gid] = loaded
                    else:
                        if gid not in cache:
                            cache[gid] = loaded
                page = cache[gid].get(page_slug)

            if page is not None:
                page.title   = page_title  # full path; prevents page being moved to root
                page.content = content
                for _attempt in range(10):
                    try:
                        page.save()
                        print(f"  → Wiki (updated): {page_title}")
                        break
                    except gitlab.exceptions.GitlabUpdateError as _ue:
                        if _ue.response_code == 404:
                            # Page vanished mid-run; re-create it fresh.
                            new_page = group.wikis.create(
                                {'title': page_title, 'content': content})
                            if cache is not None:
                                cache.setdefault(group.id, {})[new_page.slug] = new_page
                            print(f"  → Wiki (re-created): {page_title}")
                            break
                        if _ue.response_code != 400:
                            raise
                        _m2 = _re.search(r'the file (.+?)\.md', str(_ue))
                        if not _m2:
                            raise
                        _conflict_slug = _m2.group(1)
                        _fresh2 = {p.slug: p
                                   for p in group.wikis.list(all=True)}
                        if cache is not None:
                            cache[group.id] = _fresh2
                        _leaf2 = _conflict_slug.rsplit('/', 1)[-1]
                        # Only delete flat (root-level) stale pages — pages
                        # with path separators belong to other reports and
                        # must not be removed as a side-effect.
                        _stale = next(
                            (p for s, p in _fresh2.items()
                             if s != page_slug
                             and s.rsplit('/', 1)[-1] == _leaf2
                             and '/' not in s),
                            None)
                        if _stale is None:
                            # Fall back to direct GET for orphaned git files.
                            try:
                                _candidate = group.wikis.get(_conflict_slug)
                                if '/' not in _candidate.slug:
                                    _stale = _candidate
                            except Exception:
                                pass
                        if _stale is None:
                            raise _ue
                        _stale.delete()
                        _fresh2.pop(_stale.slug, None)
                else:
                    raise RuntimeError(
                        f"Could not resolve duplicate after 10 attempts: {page_title}")
            else:
                try:
                    new_page = group.wikis.create({'title': page_title, 'content': content})
                    print(f"  → Wiki: {page_title}")
                except gitlab.exceptions.GitlabCreateError as _ce:
                    if _ce.response_code != 400:
                        raise
                    # "Duplicate page: ... in the file SLUG.md" — stale flat-slug
                    # page from a previous run with a different slug algorithm.
                    # Loop: fresh-list → find flat stale page → delete → retry.
                    _cur_exc = _ce
                    new_page = None
                    for _attempt in range(10):
                        _m = _re.search(r'the file (.+?)\.md', str(_cur_exc))
                        if not _m:
                            raise _cur_exc
                        _conflict_slug = _m.group(1)
                        try:
                            _fresh_pages = group.wikis.list(all=True)
                            _fresh = {p.slug: p for p in _fresh_pages}
                        except Exception:
                            raise _cur_exc
                        if cache is not None:
                            cache[group.id] = _fresh
                        # Only remove flat (root-level) stale pages.
                        # Full-path pages belong to other reports.
                        _old = _fresh.get(_conflict_slug) \
                            if '/' not in _conflict_slug else None
                        if _old is None:
                            _leaf = _conflict_slug.rsplit('/', 1)[-1]
                            for _s, _p in _fresh.items():
                                if '/' not in _s and _s.rsplit('/', 1)[-1] == _leaf:
                                    _old = _p
                                    _conflict_slug = _s
                                    break
                        if _old is None:
                            raise _cur_exc
                        _old.delete()
                        _fresh.pop(_conflict_slug, None)
                        try:
                            new_page = group.wikis.create(
                                {'title': page_title, 'content': content})
                            print(f"  → Wiki (replaced stale): {page_title}")
                            break
                        except gitlab.exceptions.GitlabCreateError as _next:
                            if _next.response_code != 400:
                                raise
                            _cur_exc = _next
                    else:
                        raise _cur_exc
                if cache is not None:
                    gd = cache.setdefault(group.id, {})
                    gd[new_page.slug] = new_page   # actual GitLab slug
                    if new_page.slug != page_slug:
                        gd[page_slug] = new_page   # our computed slug as fallback
            return True
        except Exception as e:
            print(f"Failed to upload wiki page '{page_title}': {e}")
            return False

    def delete_all_wiki_pages(self, group):
        try:
            wiki_pages = group.wikis.list(all=True)
        except Exception as e:
            print(f"Error fetching wiki pages for group '{group.name}': {e}")
            return

        print(f"Found {len(wiki_pages)} wiki pages in the group '{group.name}'")

        for wiki_page in wiki_pages:
            try:
                print(f"Deleting wiki page: {wiki_page.title}")
                wiki_page.delete()
                print(f"Successfully deleted wiki page: {wiki_page.title}")
            except Exception as e:
                print(f"Failed to delete wiki page '{wiki_page.title}': {e}")

        print(f"All wiki pages for group '{group.name}' have been deleted.")
