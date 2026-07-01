class GroupsMixin:

    def list_groups(self):
        groups = self.gl.groups.list(owned=True, all=True)
        print(f"Groups: {len(groups)}")
        for group in groups:
            print(f"id: {group.get_id()}, name: {group.name}, web_url: {group.web_url}")
        print()

    def get_groups(self):
        partial_groups = self.gl.groups.list(owned=True, all=True)
        return [self.gl.groups.get(group.id) for group in partial_groups]

    def get_group_by_id(self, group_id):
        try:
            found_group = None
            groups = self.get_groups()
            for group in groups:
                if group.get_id() == group_id:
                    found_group = group
                    break
            return found_group
        except Exception as e:
            print(f"Error retrieving group for group_id '{group_id}'")
            return None

    def get_group_by_name(self, name):
        groups = [g for g in self.gl.groups.list(search=name, all=True) if g.name == name]
        if len(groups) == 1:
            return self.gl.groups.get(groups[0].id)
        return None

    def list_descendant_groups(self, root):
        """All groups under ``root`` at any depth, in a single paginated call.

        Uses GitLab's ``descendant_groups`` endpoint, which returns every
        descendant with ``full_path``/``name`` already populated — avoiding the
        per-subgroup ``gl.groups.get()`` N+1 that ``get_all_subgroups`` incurs.
        The returned objects are read-only projections (fine for path/name
        lookups); use ``gl.groups.get(id)`` if you need a writable group.
        """
        return list(root.descendant_groups.list(iterator=True))

    def get_all_subgroups(self, obj, include_self=True):
        group = self.get_group_by_name(obj) if isinstance(obj, str) else obj

        subgroups = group.subgroups.list(all=True)
        all_subgroups = []

        if include_self:
            all_subgroups.append(obj)

        for subgroup in subgroups:
            full_subgroup = self.gl.groups.get(subgroup.id)
            all_subgroups.append(full_subgroup)
            all_subgroups.extend(self.get_all_subgroups(full_subgroup))

        return all_subgroups
