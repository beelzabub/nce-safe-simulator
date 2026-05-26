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
            _s = _re.sub(r'[^\x00-\x7F]', '', page_title)   # drop non-ASCII
            _s = _re.sub(r'[^a-zA-Z0-9/\- ]', ' ', _s)       # special ASCII → space
            _s = _re.sub(r' +', ' ', _s).strip()              # collapse spaces
            _s = _s.replace(' ', '-')                          # spaces → dashes
            _s = _re.sub(r'-+', '-', _s)                       # collapse dashes
            page_slug = _s.strip('-')
            try:
                group.wikis.get(page_slug).delete()
            except gitlab.exceptions.GitlabGetError as e:
                if e.response_code != 404:
                    print(f"Error fetching wiki page '{page_title}': {e}")
                    return
            group.wikis.create({'title': page_title, 'content': content, 'slug': page_slug})
            print(f"  → Wiki: {page_title}")
        except Exception as e:
            print(f"Failed to upload wiki page '{page_title}': {e}")

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
