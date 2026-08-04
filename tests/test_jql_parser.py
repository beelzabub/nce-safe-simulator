"""JQL lexer + parser + AST (issue #298).

Pure-function coverage of the grammar subset: every operator and keyword,
every literal form, precedence/associativity (NOT > AND > OR), quoting edge
cases, multi-key ORDER BY, and position-aware error cases (offset and
expected-token set asserted). No network, no GitLab client.
"""
import pytest

from jql import ast, parse, tokenize, JqlSyntaxError
from jql.lexer import COMMA, EOF, LPAREN, OP, RPAREN, STRING, WORD

pytestmark = pytest.mark.unit


def where(text):
    """Parse and return the where-clause for compact assertions."""
    return parse(text).where


def err(text):
    with pytest.raises(JqlSyntaxError) as exc_info:
        parse(text)
    return exc_info.value


# ---------------------------------------------------------------------------
# Lexer
# ---------------------------------------------------------------------------

class TestLexer:

    def test_token_types_and_positions(self):
        toks = tokenize('state = opened')
        assert [(t.type, t.value, t.pos) for t in toks] == [
            (WORD, "state", 0), (OP, "=", 6), (WORD, "opened", 8), (EOF, "", 14),
        ]

    def test_all_operators_lex_as_single_tokens(self):
        toks = tokenize("= != > >= < <= ~ !~")
        assert [t.value for t in toks[:-1]] == ["=", "!=", ">", ">=", "<", "<=", "~", "!~"]
        assert all(t.type == OP for t in toks[:-1])

    def test_punctuation(self):
        toks = tokenize("(a, b)")
        assert [t.type for t in toks] == [LPAREN, WORD, COMMA, WORD, RPAREN, EOF]

    def test_words_keep_dashes_dots_colons(self):
        # scoped labels, PI ids, dates, durations, usernames all lex as one WORD
        for word in ("epic::feature", "PI-3", "2026-01-31", "-4w", "dev.user_1"):
            toks = tokenize(word)
            assert toks[0].type == WORD and toks[0].value == word

    def test_no_whitespace_needed_around_operators(self):
        toks = tokenize("weight>=5")
        assert [(t.type, t.value) for t in toks[:-1]] == [
            (WORD, "weight"), (OP, ">="), (WORD, "5"),
        ]

    def test_double_quoted_string(self):
        toks = tokenize('summary ~ "hello world"')
        assert toks[2].type == STRING and toks[2].value == "hello world"
        assert toks[2].pos == 10                      # offset of the opening quote

    def test_single_quoted_string(self):
        toks = tokenize("assignee = 'dev user'")
        assert toks[2].type == STRING and toks[2].value == "dev user"

    def test_empty_string(self):
        toks = tokenize('summary ~ ""')
        assert toks[2].type == STRING and toks[2].value == ""

    def test_other_quote_type_inside_string(self):
        assert tokenize('x = "it\'s"')[2].value == "it's"
        assert tokenize("x = 'say \"hi\"'")[2].value == 'say "hi"'

    def test_escaped_quote_and_backslash(self):
        assert tokenize(r'x = "a \" b"')[2].value == 'a " b'
        assert tokenize(r'x = "a \\ b"')[2].value == "a \\ b"

    def test_escape_sequences(self):
        assert tokenize(r'x = "a\tb\nc"')[2].value == "a\tb\nc"
        assert tokenize(r'x = "é"')[2].value == "é"

    def test_unknown_escape_kept_literally(self):
        assert tokenize(r'x = "a\qb"')[2].value == "aqb"

    def test_unterminated_string_error_offset(self):
        with pytest.raises(JqlSyntaxError) as exc_info:
            tokenize('state = "opened')
        assert exc_info.value.offset == 8
        assert exc_info.value.found == "end of query"

    def test_lone_bang_error(self):
        with pytest.raises(JqlSyntaxError) as exc_info:
            tokenize("state ! opened")
        e = exc_info.value
        assert e.offset == 6 and e.found == "!"
        assert set(e.expected) == {"!=", "!~"}

    def test_empty_input_is_just_eof(self):
        assert [t.type for t in tokenize("")] == [EOF]
        assert [t.type for t in tokenize("   \t\n ")] == [EOF]


# ---------------------------------------------------------------------------
# Comparison operators
# ---------------------------------------------------------------------------

class TestOperators:

    @pytest.mark.parametrize("op", ["=", "!=", ">", ">=", "<", "<=", "~", "!~"])
    def test_every_comparison_operator(self, op):
        node = where("weight %s 5" % op)
        assert node == ast.Comparison(field="weight", op=op, value=ast.Number(5))

    def test_comparison_pos_is_field_offset(self):
        node = where("  weight >= 5")
        assert node.pos == 2
        assert node.value.pos == 12

    def test_in_list(self):
        node = where("state IN (opened, closed)")
        assert node == ast.InList(
            field="state",
            values=(ast.String("opened"), ast.String("closed")),
            negated=False,
        )

    def test_not_in_list(self):
        node = where('assignee NOT IN (dev-user-1, "dev user 2")')
        assert node == ast.InList(
            field="assignee",
            values=(ast.String("dev-user-1"), ast.String("dev user 2", quoted=True)),
            negated=True,
        )

    def test_in_single_element_list(self):
        node = where("labels in (blocked)")
        assert node == ast.InList(field="labels", values=(ast.String("blocked"),))

    def test_is_empty(self):
        assert where("assignee IS EMPTY") == ast.IsEmpty(field="assignee")

    def test_is_null_is_synonym(self):
        assert where("assignee IS NULL") == ast.IsEmpty(field="assignee")

    def test_is_not_empty(self):
        assert where("due IS NOT EMPTY") == ast.IsEmpty(field="due", negated=True)

    def test_equals_empty_keyword_value(self):
        assert where("assignee = EMPTY") == ast.Comparison(
            field="assignee", op="=", value=ast.Empty())

    def test_not_equals_null_keyword_value(self):
        assert where("assignee != null") == ast.Comparison(
            field="assignee", op="!=", value=ast.Empty())


# ---------------------------------------------------------------------------
# Keywords: case-insensitivity, quoted fields
# ---------------------------------------------------------------------------

class TestKeywords:

    @pytest.mark.parametrize("q", [
        "a = 1 AND b = 2", "a = 1 and b = 2", "a = 1 And b = 2",
    ])
    def test_keywords_case_insensitive(self, q):
        assert isinstance(where(q), ast.And)

    def test_mixed_case_everything(self):
        query = parse("a In (1) Or b Is Not Empty oRdEr By c dEsC")
        assert isinstance(query.where, ast.Or)
        assert query.order_by == (ast.SortKey(field="c", direction="DESC"),)

    def test_quoted_field_name(self):
        node = where('"order" = shipped')
        assert node == ast.Comparison(field="order", op="=",
                                      value=ast.String("shipped"))

    def test_quoted_keyword_is_a_plain_value(self):
        node = where('label = "EMPTY"')
        assert node == ast.Comparison(field="label", op="=",
                                      value=ast.String("EMPTY", quoted=True))


# ---------------------------------------------------------------------------
# Precedence and associativity: NOT > AND > OR
# ---------------------------------------------------------------------------

class TestPrecedence:

    C_A = ast.Comparison(field="a", op="=", value=ast.Number(1))
    C_B = ast.Comparison(field="b", op="=", value=ast.Number(2))
    C_C = ast.Comparison(field="c", op="=", value=ast.Number(3))

    def test_and_binds_tighter_than_or(self):
        assert where("a = 1 OR b = 2 AND c = 3") == ast.Or(
            operands=(self.C_A, ast.And(operands=(self.C_B, self.C_C))))

    def test_and_binds_tighter_than_or_left_side(self):
        assert where("a = 1 AND b = 2 OR c = 3") == ast.Or(
            operands=(ast.And(operands=(self.C_A, self.C_B)), self.C_C))

    def test_not_binds_tighter_than_and(self):
        assert where("NOT a = 1 AND b = 2") == ast.And(
            operands=(ast.Not(operand=self.C_A), self.C_B))

    def test_chained_and_is_flat_nary(self):
        assert where("a = 1 AND b = 2 AND c = 3") == ast.And(
            operands=(self.C_A, self.C_B, self.C_C))

    def test_chained_or_is_flat_nary(self):
        assert where("a = 1 OR b = 2 OR c = 3") == ast.Or(
            operands=(self.C_A, self.C_B, self.C_C))

    def test_parens_override_precedence(self):
        assert where("(a = 1 OR b = 2) AND c = 3") == ast.And(
            operands=(ast.Or(operands=(self.C_A, self.C_B)), self.C_C))

    def test_parenthesized_and_keeps_its_own_node(self):
        assert where("(a = 1 AND b = 2) AND c = 3") == ast.And(
            operands=(ast.And(operands=(self.C_A, self.C_B)), self.C_C))

    def test_double_negation(self):
        assert where("NOT NOT a = 1") == ast.Not(operand=ast.Not(operand=self.C_A))

    def test_not_applies_to_parenthesized_group(self):
        assert where("NOT (a = 1 OR b = 2)") == ast.Not(
            operand=ast.Or(operands=(self.C_A, self.C_B)))

    def test_nested_parens(self):
        assert where("((a = 1))") == self.C_A


# ---------------------------------------------------------------------------
# Literal forms
# ---------------------------------------------------------------------------

class TestLiterals:

    def test_quoted_string(self):
        assert where('labels = "epic::feature"').value == ast.String(
            "epic::feature", quoted=True)

    def test_unquoted_string(self):
        assert where("state = opened").value == ast.String("opened")

    def test_unquoted_string_with_dash(self):
        assert where("piid = PI-3").value == ast.String("PI-3")

    def test_integer(self):
        assert where("weight = 5").value == ast.Number(5)
        assert isinstance(where("weight = 5").value.value, int)

    def test_float(self):
        assert where("business_value = 3.5").value == ast.Number(3.5)

    def test_negative_number(self):
        assert where("delta = -2").value == ast.Number(-2)

    def test_iso_date(self):
        assert where("created >= 2026-01-31").value == ast.DateLiteral("2026-01-31")

    def test_slash_date(self):
        assert where("created >= 2026/01/31").value == ast.DateLiteral("2026/01/31")

    def test_duration_negative_weeks(self):
        assert where("updated >= -4w").value == ast.Duration("-4w")

    @pytest.mark.parametrize("dur", ["1d", "+2h", "30m", "-10D"])
    def test_duration_forms(self, dur):
        assert where("updated >= %s" % dur).value == ast.Duration(dur)

    def test_word_ending_in_unit_letter_is_a_string(self):
        # 'w1d' has no leading digits -> not a duration
        assert where("x = w1d").value == ast.String("w1d")

    def test_mixed_list(self):
        node = where('x IN (1, "two", 2026-01-01, -4w, three)')
        assert node.values == (
            ast.Number(1),
            ast.String("two", quoted=True),
            ast.DateLiteral("2026-01-01"),
            ast.Duration("-4w"),
            ast.String("three"),
        )


# ---------------------------------------------------------------------------
# Functions
# ---------------------------------------------------------------------------

class TestFunctions:

    def test_zero_arg_function(self):
        assert where("created <= now()").value == ast.Function(name="now")

    def test_current_user(self):
        assert where("assignee = currentUser()").value == ast.Function(
            name="currentUser")

    def test_function_with_negative_int_arg(self):
        assert where("created >= startOfDay(-1)").value == ast.Function(
            name="startOfDay", args=(ast.Number(-1),))

    def test_function_with_string_arg(self):
        assert where('created >= startOfWeek("-1d")').value == ast.Function(
            name="startOfWeek", args=(ast.String("-1d", quoted=True),))

    def test_function_with_duration_arg(self):
        assert where("created >= endOfMonth(-1w)").value == ast.Function(
            name="endOfMonth", args=(ast.Duration("-1w"),))

    def test_function_name_keeps_original_spelling(self):
        assert where("x = StartOfYear()").value.name == "StartOfYear"

    def test_function_inside_in_list(self):
        node = where("assignee IN (currentUser(), dev-user-1)")
        assert node.values == (ast.Function(name="currentUser"),
                               ast.String("dev-user-1"))

    def test_multi_arg_function(self):
        assert where("x = f(1, 2)").value == ast.Function(
            name="f", args=(ast.Number(1), ast.Number(2)))

    def test_unclosed_function_args_error(self):
        e = err("created >= startOfDay(-1")
        assert e.offset == 24 and set(e.expected) == {",", ")"}


# ---------------------------------------------------------------------------
# ORDER BY
# ---------------------------------------------------------------------------

class TestOrderBy:

    def test_single_key_default_asc(self):
        query = parse("state = opened ORDER BY due_date")
        assert query.order_by == (ast.SortKey(field="due_date", direction="ASC"),)

    def test_explicit_directions(self):
        query = parse("ORDER BY weight DESC, created ASC")
        assert query.order_by == (
            ast.SortKey(field="weight", direction="DESC"),
            ast.SortKey(field="created", direction="ASC"),
        )

    def test_multi_key_mixed_defaults(self):
        query = parse("x = 1 order by a desc, b, c asc")
        assert query.order_by == (
            ast.SortKey(field="a", direction="DESC"),
            ast.SortKey(field="b", direction="ASC"),
            ast.SortKey(field="c", direction="ASC"),
        )

    def test_order_by_only_query_has_no_where(self):
        query = parse("ORDER BY created DESC")
        assert query.where is None
        assert query.order_by == (ast.SortKey(field="created", direction="DESC"),)

    def test_quoted_sort_field(self):
        assert parse('ORDER BY "order"').order_by == (ast.SortKey(field="order"),)

    def test_sort_key_pos(self):
        query = parse("ORDER BY created")
        assert query.order_by[0].pos == 9

    def test_empty_query(self):
        assert parse("") == ast.Query(where=None, order_by=())
        assert parse("   ") == ast.Query(where=None, order_by=())


# ---------------------------------------------------------------------------
# Error cases: offset + expected-token set asserted
# ---------------------------------------------------------------------------

class TestErrors:

    def test_missing_value(self):
        e = err("state =")
        assert e.offset == 7
        assert e.found == "end of query"
        assert set(e.expected) == {"a value"}

    def test_missing_operator(self):
        e = err("state opened")
        assert e.offset == 6 and e.found == "opened"
        assert set(e.expected) == {"=", "!=", ">", ">=", "<", "<=", "~", "!~",
                                   "IN", "NOT IN", "IS"}

    def test_trailing_and(self):
        e = err("state = opened AND")
        assert e.offset == 18 and e.found == "end of query"
        assert "a field name" in e.expected

    def test_unclosed_paren(self):
        e = err("(a = 1")
        assert e.offset == 6
        assert set(e.expected) == {"AND", "OR", ")"}

    def test_two_clauses_without_connector(self):
        e = err("a = 1 b = 2")
        assert e.offset == 6 and e.found == "b"
        assert set(e.expected) == {"AND", "OR", "ORDER BY", "end of query"}

    def test_order_without_by(self):
        e = err("a = 1 ORDER created")
        assert e.offset == 12 and e.found == "created"
        assert set(e.expected) == {"BY"}

    def test_in_without_parens(self):
        e = err("state in opened")
        assert e.offset == 9 and set(e.expected) == {"("}

    def test_empty_in_list(self):
        e = err("state in ()")
        assert e.offset == 10 and set(e.expected) == {"a value"}

    def test_in_list_missing_close(self):
        e = err("state in (a, b")
        assert e.offset == 14 and set(e.expected) == {",", ")"}

    def test_is_without_empty(self):
        e = err("assignee is opened")
        assert e.offset == 12
        assert set(e.expected) == {"EMPTY", "NULL", "NOT"}

    def test_is_not_without_empty(self):
        e = err("assignee is not opened")
        assert e.offset == 16
        assert set(e.expected) == {"EMPTY", "NULL"}

    def test_not_after_field_requires_in(self):
        e = err("assignee not = x")
        assert e.offset == 13 and set(e.expected) == {"IN"}

    def test_reserved_word_as_field(self):
        e = err("and = 1")
        assert e.offset == 0 and e.found == "and"
        assert set(e.expected) == {"a field name"}

    def test_reserved_word_as_value(self):
        e = err("state = order")
        assert e.offset == 8 and set(e.expected) == {"a value"}

    def test_dangling_not(self):
        e = err("NOT")
        assert e.offset == 3 and set(e.expected) == {"a field name"}

    def test_trailing_garbage_after_order_by(self):
        e = err("ORDER BY a x")
        assert e.offset == 11 and e.found == "x"
        assert set(e.expected) == {",", "end of query"}

    def test_lone_close_paren(self):
        e = err(")")
        assert e.offset == 0 and set(e.expected) == {"a field name"}

    def test_error_message_contains_offset_and_found(self):
        e = err("state =")
        assert "offset 7" in str(e)
        assert "a value" in str(e)

    def test_offsets_survive_leading_whitespace(self):
        e = err("   state %")
        assert e.offset == 9


# ---------------------------------------------------------------------------
# Full-query integration (the epic's motivating examples)
# ---------------------------------------------------------------------------

class TestFullQueries:

    def test_epic_example_one(self):
        q = parse('type = epic AND labels = "epic::feature" AND weight >= 5 '
                  'AND updated >= -4w ORDER BY due_date ASC')
        assert q.where == ast.And(operands=(
            ast.Comparison(field="type", op="=", value=ast.String("epic")),
            ast.Comparison(field="labels", op="=",
                           value=ast.String("epic::feature", quoted=True)),
            ast.Comparison(field="weight", op=">=", value=ast.Number(5)),
            ast.Comparison(field="updated", op=">=", value=ast.Duration("-4w")),
        ))
        assert q.order_by == (ast.SortKey(field="due_date", direction="ASC"),)

    def test_epic_example_two(self):
        q = parse("state = opened AND (assignee = dev-user-1 OR assignee IS EMPTY) "
                  "AND piid = PI-3")
        assert q.where == ast.And(operands=(
            ast.Comparison(field="state", op="=", value=ast.String("opened")),
            ast.Or(operands=(
                ast.Comparison(field="assignee", op="=",
                               value=ast.String("dev-user-1")),
                ast.IsEmpty(field="assignee"),
            )),
            ast.Comparison(field="piid", op="=", value=ast.String("PI-3")),
        ))
        assert q.order_by == ()

    def test_module_has_no_gitlab_imports(self):
        # the contract: jql never imports the client or anything with I/O
        import sys
        for mod in ("jql", "jql.lexer", "jql.parser", "jql.ast", "jql.dates"):
            module = sys.modules[mod]
            source_names = set(getattr(module, "__dict__", {}))
            assert "gitlab" not in source_names
            assert "requests" not in source_names
