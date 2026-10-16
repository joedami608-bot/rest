"""Tokenizer. Identifiers starting with an uppercase letter are type/constructor names."""

from dataclasses import dataclass

from .errors import SyntaxErr

KEYWORDS = {"fn", "let", "var", "type", "match", "if", "else", "while", "true", "false", "and", "or", "not"}

OPERATORS = [  # longest first
    "=>", "->", "::", "++", "==", "!=", "<=", ">=", "|>",
    "+", "-", "*", "/", "%", "<", ">", "=", "|",
    "(", ")", "{", "}", "[", "]", ",", ";", ":",
]


@dataclass(frozen=True)
class Token:
    kind: str  # INT STRING IDENT UPPER KEYWORD OP EOF
    value: object
    line: int
    col: int


def tokenize(src):
    toks = []
    i, line, col = 0, 1, 1
    n = len(src)

    def bump(k):
        nonlocal i, line, col
        for _ in range(k):
            if src[i] == "\n":
                line, col = line + 1, 1
            else:
                col += 1
            i += 1

    while True:
        # whitespace and comments
        while i < n:
            if src[i] in " \t\r\n":
                bump(1)
            elif src[i] == "#":
                while i < n and src[i] != "\n":
                    bump(1)
            else:
                break
        if i >= n:
            toks.append(Token("EOF", None, line, col))
            return toks

        start_line, start_col, ch = line, col, src[i]
        if ch.isdigit():
            j = i
            while j < n and (src[j].isdigit() or src[j] == "_"):
                j += 1
            text = src[i:j]
            bump(j - i)
            toks.append(Token("INT", int(text.replace("_", "")), start_line, start_col))
        elif ch.isalpha() or ch == "_":
            j = i
            while j < n and (src[j].isalnum() or src[j] == "_"):
                j += 1
            text = src[i:j]
            bump(j - i)
            kind = "KEYWORD" if text in KEYWORDS else "UPPER" if text[0].isupper() else "IDENT"
            toks.append(Token(kind, text, start_line, start_col))
        elif ch == '"':
            bump(1)
            buf = []
            escapes = {"n": "\n", "t": "\t", '"': '"', "\\": "\\"}
            while True:
                if i >= n or src[i] == "\n":
                    raise SyntaxErr("unterminated string literal", start_line, start_col)
                c = src[i]
                if c == '"':
                    bump(1)
                    break
                if c == "\\":
                    if i + 1 >= n or src[i + 1] not in escapes:
                        raise SyntaxErr("invalid escape sequence", line, col)
                    buf.append(escapes[src[i + 1]])
                    bump(2)
                else:
                    buf.append(c)
                    bump(1)
            toks.append(Token("STRING", "".join(buf), start_line, start_col))
        else:
            for op in OPERATORS:
                if src.startswith(op, i):
                    bump(len(op))
                    toks.append(Token("OP", op, start_line, start_col))
                    break
            else:
                raise SyntaxErr(f"unexpected character {ch!r}", start_line, start_col)
