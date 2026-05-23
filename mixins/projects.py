class ProjectsMixin:

    def list_projects(self):
        projects = self.gl.projects.list(owned=True, all=True)
        print(f"Projects: {len(projects)}")
        for project in projects:
            print(f"id: {project.get_id()}, name: {project.name}, web_url: {project.web_url}")
        print()

    def list_projects_recursive(self, group_name, level=0):
        group = self.get_group_by_name(group_name)
        if group is None:
            return

        print(f"{'    ' * level}Group: {group.name} (id: {group.id})")
        projects = group.projects.list(all=True)
        for project in projects:
            print(f"{'    ' * (level + 1)}Project id: {project.id}, Name: {project.name}")

        subgroups = group.subgroups.list(all=True)
        for subgroup in subgroups:
            self.list_projects_recursive(subgroup.name, level + 1)

    def get_projects(self):
        partial_projects = self.gl.projects.list(owned=True, all=True)
        return [self.gl.projects.get(project.id) for project in partial_projects]

    def get_project_by_name(self, name):
        project = None
        projects = [p for p in self.gl.projects.list(owned=True, all=True) if p.name == name]

        if len(projects) == 1:
            project = self.gl.projects.get(projects[0].get_id())
        else:
            print(f"get_project_by_name: projects len: {len(projects)}")

        return project
