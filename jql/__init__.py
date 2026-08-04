"""JQL query engine package (epic #297).

Dependency-free modules: no network I/O happens anywhere in this package;
transport stays in ``mixins/utils.py`` (``graphql_query``) and is invoked by
the executor mixin, not from here.
"""
