class LabelsMixin:

    def create_and_apply_labels(self, target, labels):
        try:
            if isinstance(labels, str):
                labels = [label.strip() for label in labels.split(",")]

            if hasattr(target, 'labels'):
                create_label = lambda name: target.labels.create({"name": name, "color": "#4287f5"})
            elif hasattr(target, 'group_labels'):
                create_label = lambda name: target.group_labels.create({"name": name, "color": "#4287f5"})
            else:
                print(f"Unsupported target type: {type(target)}")
                return

            for label in labels:
                try:
                    create_label(label)
                    print(f"Label '{label}' created successfully.")
                except Exception as e:
                    print(f"Failed to create label '{label}': {e}")

        except Exception as e:
            print(f"An error occurred: {e}")

    def delete_all_labels(self, target):
        try:
            if hasattr(target, 'labels'):
                list_labels = target.labels.list(all=True)
                delete_label = lambda label: label.delete()
            elif hasattr(target, 'group_labels'):
                list_labels = target.group_labels.list(all=True)
                delete_label = lambda label: label.delete()
            else:
                print("Unsupported target type. Please provide a valid GitLab group or project object.")
                return

            print(f"Found {len(list_labels)} labels to delete.")
            for label in list_labels:
                try:
                    print(f"Deleting label: {label.name}")
                    delete_label(label)
                except Exception as e:
                    print(f"Failed to delete label '{label.name}': {e}")

            print(f"All labels for the target '{target.name}' have been deleted.")
            print()

        except Exception as e:
            print(f"An error occurred: {e}")
