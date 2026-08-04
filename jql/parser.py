"""Recursive-descent parser for the JQL grammar subset (issue #298).

Grammar (keywords case-insensitive; precedence NOT > AND > OR):

    query      := [or_expr] [ORDER BY sort_key ("," sort_key)*]
    sort_key   := field [ASC | DESC]
    or_expr    := and_expr (OR and_expr)*
    and_expr   := not_expr (AND not_expr)*
    not_expr   := NOT not_expr | primary
    primary    := "(" or_expr ")" | predicate
    predicate  := field ( op value            op in = != > >= < <= ~ !~
                        | [NOT] IN "(" value ("," value)* ")"
                        | IS [NOT] (EMPTY | NULL) )
    value      := STRING | EMPTY | NULL | function | number | date
                | duration | unquoted string
    function   := WORD "(" [value ("," value)*] ")"
    field      := WORD (non-reserved) | STRING

All errors are JqlSyntaxError carrying the 0-based offset, what was found,
and the expected-token set — JQL-style position-aware messages.
"""
import re

from . import ast
from .lexer import (
    COMMA,
    EOF,
    LPAREN,
    OP,
    RPAREN,
    STRING,
    WORD,
    JqlSyntaxError,
    tokenize,
)

#: Words that cannot be used unquoted as field names or values.
RESERVED = frozenset(
    {"AND", "OR", "NOT", "IN", "IS", "EMPTY", "NULL", "ORDER", "BY", "ASC", "DESC"}
)

COMPARISON_OPS = ("=", "!=", ">", ">=", "<", "<=", "~", "!~")

_NUMBER_RE = re.compile(r"^[+-]?\d+(\.\d+)?$")
_DURATION_RE = re.compile(r"^[+-]?\d+[wdhmWDHM]$")
_DATE_RE = re.compile(r"^\d{4}[-/]\d{1,2}[-/]\d{1,2}$")


def parse(text):
    """Parse a JQL query string into an ast.Query. Raises JqlSyntaxError."""
    return _Parser(tokenize(text)).parse_query()


class _Parser:

    def __init__(self, tokens):
        self.tokens = tokens
        self.i = 0

    # -- token plumbing -----------------------------------------------------

    @property
    def cur(self):
        return self.tokens[self.i]

    def advance(self):
        tok = self.tokens[self.i]
        if tok.type != EOF:
            self.i += 1
        return tok

    def keyword(self, tok=None):
        """The uppercased keyword a WORD token spells, else None."""
        tok = tok or self.cur
        return tok.value.upper() if tok.type == WORD else None

    def error(self, expected, tok=None):
        tok = tok or self.cur
        found = "end of query" if tok.type == EOF else tok.value
        expected = tuple(expected)
        raise JqlSyntaxError(
            "Expected %s but found '%s' at offset %d"
            % (" or ".join("'%s'" % e for e in expected), found, tok.pos),
            offset=tok.pos,
            found=found,
            expected=expected,
        )

    # -- query --------------------------------------------------------------

    def parse_query(self):
        where = None
        if self.cur.type != EOF and self.keyword() != "ORDER":
            where = self.parse_or()
        order_by = ()
        if self.keyword() == "ORDER":
            order_by = self.parse_order_by()
        if self.cur.type != EOF:
            if order_by:
                self.error((",", "end of query"))
            if where is not None:
                self.error(("AND", "OR", "ORDER BY", "end of query"))
            self.error(("ORDER BY", "end of query"))
        return ast.Query(where=where, order_by=order_by)

    def parse_order_by(self):
        self.advance()  # ORDER
        if self.keyword() != "BY":
            self.error(("BY",))
        self.advance()
        keys = [self.parse_sort_key()]
        while self.cur.type == COMMA:
            self.advance()
            keys.append(self.parse_sort_key())
        return tuple(keys)

    def parse_sort_key(self):
        field_tok = self.parse_field_name()
        direction = "ASC"
        if self.keyword() in ("ASC", "DESC"):
            direction = self.keyword()
            self.advance()
        return ast.SortKey(field=field_tok.value, direction=direction,
                           pos=field_tok.pos)

    def parse_field_name(self):
        tok = self.cur
        if tok.type == STRING:
            return self.advance()
        if tok.type == WORD and self.keyword(tok) not in RESERVED:
            return self.advance()
        self.error(("a field name",))

    # -- boolean expressions (NOT > AND > OR) -------------------------------

    def parse_or(self):
        parts = [self.parse_and()]
        while self.keyword() == "OR":
            self.advance()
            parts.append(self.parse_and())
        if len(parts) == 1:
            return parts[0]
        return ast.Or(operands=tuple(parts), pos=parts[0].pos)

    def parse_and(self):
        parts = [self.parse_not()]
        while self.keyword() == "AND":
            self.advance()
            parts.append(self.parse_not())
        if len(parts) == 1:
            return parts[0]
        return ast.And(operands=tuple(parts), pos=parts[0].pos)

    def parse_not(self):
        if self.keyword() == "NOT":
            tok = self.advance()
            return ast.Not(operand=self.parse_not(), pos=tok.pos)
        return self.parse_primary()

    def parse_primary(self):
        if self.cur.type == LPAREN:
            self.advance()
            expr = self.parse_or()
            if self.cur.type != RPAREN:
                self.error(("AND", "OR", ")"))
            self.advance()
            return expr
        return self.parse_predicate()

    # -- predicates ---------------------------------------------------------

    def parse_predicate(self):
        field_tok = self.parse_field_name()
        field = field_tok.value
        tok = self.cur

        if tok.type == OP:
            self.advance()
            value = self.parse_value()
            return ast.Comparison(field=field, op=tok.value, value=value,
                                  pos=field_tok.pos)

        kw = self.keyword()
        if kw == "IN":
            self.advance()
            values = self.parse_value_list()
            return ast.InList(field=field, values=values, negated=False,
                              pos=field_tok.pos)
        if kw == "NOT":
            self.advance()
            if self.keyword() != "IN":
                self.error(("IN",))
            self.advance()
            values = self.parse_value_list()
            return ast.InList(field=field, values=values, negated=True,
                              pos=field_tok.pos)
        if kw == "IS":
            self.advance()
            negated = False
            if self.keyword() == "NOT":
                self.advance()
                negated = True
            if self.keyword() in ("EMPTY", "NULL"):
                self.advance()
                return ast.IsEmpty(field=field, negated=negated,
                                   pos=field_tok.pos)
            if negated:
                self.error(("EMPTY", "NULL"))
            self.error(("EMPTY", "NULL", "NOT"))

        self.error(COMPARISON_OPS + ("IN", "NOT IN", "IS"))

    # -- values -------------------------------------------------------------

    def parse_value_list(self):
        if self.cur.type != LPAREN:
            self.error(("(",))
        self.advance()
        values = [self.parse_value()]
        while self.cur.type == COMMA:
            self.advance()
            values.append(self.parse_value())
        if self.cur.type != RPAREN:
            self.error((",", ")"))
        self.advance()
        return tuple(values)

    def parse_value(self):
        tok = self.cur
        if tok.type == STRING:
            self.advance()
            return ast.String(value=tok.value, quoted=True, pos=tok.pos)
        if tok.type == WORD:
            kw = self.keyword(tok)
            if kw in ("EMPTY", "NULL"):
                self.advance()
                return ast.Empty(pos=tok.pos)
            if kw in RESERVED:
                self.error(("a value",))
            self.advance()
            if self.cur.type == LPAREN and self.cur.pos == tok.pos + len(tok.value):
                return self.parse_function(tok)
            return self.classify_word(tok)
        self.error(("a value",))

    def parse_function(self, name_tok):
        self.advance()  # (
        args = []
        if self.cur.type != RPAREN:
            args.append(self.parse_value())
            while self.cur.type == COMMA:
                self.advance()
                args.append(self.parse_value())
        if self.cur.type != RPAREN:
            self.error((",", ")"))
        self.advance()
        return ast.Function(name=name_tok.value, args=tuple(args),
                            pos=name_tok.pos)

    @staticmethod
    def classify_word(tok):
        """Classify an unquoted word into the most specific literal node."""
        text = tok.value
        if _DURATION_RE.match(text):
            return ast.Duration(value=text, pos=tok.pos)
        if _NUMBER_RE.match(text):
            value = float(text) if "." in text else int(text)
            return ast.Number(value=value, pos=tok.pos)
        if _DATE_RE.match(text):
            return ast.DateLiteral(value=text, pos=tok.pos)
        return ast.String(value=text, quoted=False, pos=tok.pos)
