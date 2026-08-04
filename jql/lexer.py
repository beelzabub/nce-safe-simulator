"""JQL lexer: source text -> token stream.

A pure function of the input string — no I/O, no GitLab dependency. Keywords
(AND, OR, NOT, IN, IS, EMPTY, NULL, ORDER, BY, ASC, DESC) are *not* resolved
here: they surface as WORD tokens and the parser matches them
case-insensitively, so quoted strings can always be used verbatim as values.

Token types:
    WORD    unquoted run of value characters (fields, keywords, numbers,
            dates, durations, scoped labels like ``epic::feature``)
    STRING  quoted string ('...' or "...") with backslash escapes
    OP      one of  =  !=  >  >=  <  <=  ~  !~
    LPAREN, RPAREN, COMMA, EOF
"""
from dataclasses import dataclass

WORD = "WORD"
STRING = "STRING"
OP = "OP"
LPAREN = "LPAREN"
RPAREN = "RPAREN"
COMMA = "COMMA"
EOF = "EOF"

#: Characters that terminate an unquoted word. Everything else (letters,
#: digits, ``-``, ``.``, ``_``, ``:``) is a word character, which is what lets
#: ``-4w``, ``2026-01-31``, ``PI-3`` and ``epic::feature`` lex as single words.
_WORD_BREAK = set(" \t\r\n(),\"'=!<>~")

_ESCAPES = {
    '"': '"',
    "'": "'",
    "\\": "\\",
    "n": "\n",
    "t": "\t",
    "r": "\r",
}


class JqlSyntaxError(ValueError):
    """A lexing or parsing error with position + expectation metadata.

    Attributes:
        offset:   0-based character offset into the query string.
        found:    human-readable description of what was found.
        expected: tuple of human-readable descriptions of what was valid here.
    """

    def __init__(self, message, offset, found=None, expected=()):
        self.offset = offset
        self.found = found
        self.expected = tuple(expected)
        super().__init__(message)


@dataclass(frozen=True)
class Token:
    type: str
    value: str
    pos: int


def _lex_string(text, i):
    """Lex a quoted string starting at ``i`` (which holds the quote char)."""
    quote = text[i]
    start = i
    i += 1
    chars = []
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == quote:
            return Token(STRING, "".join(chars), start), i + 1
        if ch == "\\":
            if i + 1 >= n:
                break  # dangling backslash at end -> unterminated
            esc = text[i + 1]
            if esc == "u" and i + 5 < n:
                hex_digits = text[i + 2:i + 6]
                try:
                    chars.append(chr(int(hex_digits, 16)))
                    i += 6
                    continue
                except ValueError:
                    pass  # not a valid \uXXXX -> fall through, keep literally
            chars.append(_ESCAPES.get(esc, esc))
            i += 2
            continue
        chars.append(ch)
        i += 1
    raise JqlSyntaxError(
        "Unterminated string starting at offset %d" % start,
        offset=start,
        found="end of query",
        expected=("closing %s" % quote,),
    )


def tokenize(text):
    """Tokenize a JQL query string. Returns a list ending with an EOF token.

    Raises JqlSyntaxError (with .offset) on unterminated strings and stray
    operator characters.
    """
    tokens = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch in " \t\r\n":
            i += 1
            continue
        if ch == "(":
            tokens.append(Token(LPAREN, "(", i))
            i += 1
        elif ch == ")":
            tokens.append(Token(RPAREN, ")", i))
            i += 1
        elif ch == ",":
            tokens.append(Token(COMMA, ",", i))
            i += 1
        elif ch in "\"'":
            tok, i = _lex_string(text, i)
            tokens.append(tok)
        elif ch == "!":
            if i + 1 < n and text[i + 1] in "=~":
                tokens.append(Token(OP, text[i:i + 2], i))
                i += 2
            else:
                raise JqlSyntaxError(
                    "Unexpected character '!' at offset %d" % i,
                    offset=i,
                    found="!",
                    expected=("!=", "!~"),
                )
        elif ch in "<>":
            if i + 1 < n and text[i + 1] == "=":
                tokens.append(Token(OP, text[i:i + 2], i))
                i += 2
            else:
                tokens.append(Token(OP, ch, i))
                i += 1
        elif ch in "=~":
            tokens.append(Token(OP, ch, i))
            i += 1
        else:
            start = i
            while i < n and text[i] not in _WORD_BREAK:
                i += 1
            tokens.append(Token(WORD, text[start:i], start))
    tokens.append(Token(EOF, "", n))
    return tokens
