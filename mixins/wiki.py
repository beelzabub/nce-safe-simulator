import gitlab


class WikiMixin:

    def upload_to_wiki(self, group, page_title, content):
        try:
            page_slug = page_title.replace(" ", "-").lower()
            try:
                group.wikis.get(page_slug).delete()
            except gitlab.exceptions.GitlabGetError as e:
                if e.response_code != 404:
                    print(f"Error fetching wiki page '{page_title}': {e}")
                    return
            group.wikis.create({'title': page_title, 'content': content})
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
