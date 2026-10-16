"""Lexer: turns source text into a stream of tokens with line/column info."""

from dataclasses import dataclass

from .errors import MiniSyntaxError

KEYWORDS = {
    "let", "fn", "if", "else", "while", "for", "in", "return",
    "true", "false", "nil", "and", "or", "not", "break", "continue",
}

# Longest operators first so "==" wins over "=".
OPERATORS = [
    "==", "!=", "<=", ">=", "->", "..", "|>",
    "+", "-", "*", "/", "%", "<", ">", "=",
    "(", ")", "{", "}", "[", "]", ",", ";", ":", ".",
]


@dataclass(frozen=True)
class Token:
    kind: str      # NUMBER, STRING, IDENT, KEYWORD, OP, EOF
    value: object
    line: int
    col: int

    def __repr__(self):
        return f"Token({self.kind}, {self.value!r}, {self.line}:{self.col})"


class Lexer:
    def __init__(self, source: str):
        self.src = source
        self.pos = 0
        self.line = 1
        self.col = 1

    def _peek(self, offset=0):
        i = self.pos + offset
        return self.src[i] if i < len(self.src) else ""

    def _advance(self):
        ch = self.src[self.pos]
        self.pos += 1
        if ch == "\n":
            self.line += 1
            self.col = 1
        else:
            self.col += 1
        return ch

    def _skip_trivia(self):
        while self.pos < len(self.src):
            ch = self._peek()
            if ch in " \t\r\n":
                self._advance()
            elif ch == "#":
                while self.pos < len(self.src) and self._peek() != "\n":
                    self._advance()
            else:
                break

    def tokens(self):
        out = []
        while True:
            self._skip_trivia()
            line, col = self.line, self.col
            if self.pos >= len(self.src):
                out.append(Token("EOF", None, line, col))
                return out
            ch = self._peek()
            if ch.isdigit():
                out.append(self._number(line, col))
            elif ch.isalpha() or ch == "_":
                out.append(self._ident(line, col))
            elif ch == '"':
                out.append(self._string(line, col))
            else:
                for op in OPERATORS:
                    if self.src.startswith(op, self.pos):
                        for _ in op:
                            self._advance()
                        out.append(Token("OP", op, line, col))
                        break
                else:
                    raise MiniSyntaxError(f"unexpected character {ch!r}", line, col)

    def _number(self, line, col):
        start = self.pos
        while self._peek().isdigit():
            self._advance()
        is_float = False
        # Only treat "." as a decimal point if followed by a digit (keeps "1..5" a range).
        if self._peek() == "." and self._peek(1).isdigit():
            is_float = True
            self._advance()
            while self._peek().isdigit():
                self._advance()
        text = self.src[start:self.pos]
        return Token("NUMBER", float(text) if is_float else int(text), line, col)

    def _ident(self, line, col):
        start = self.pos
        while self._peek().isalnum() or self._peek() == "_":
            self._advance()
        text = self.src[start:self.pos]
        return Token("KEYWORD" if text in KEYWORDS else "IDENT", text, line, col)

    def _string(self, line, col):
        self._advance()  # opening quote
        chars = []
        escapes = {"n": "\n", "t": "\t", '"': '"', "\\": "\\"}
        while True:
            if self.pos >= len(self.src):
                raise MiniSyntaxError("unterminated string", line, col)
            ch = self._advance()
            if ch == '"':
                break
            if ch == "\\":
                if self.pos >= len(self.src):
                    raise MiniSyntaxError("unterminated string", line, col)
                esc = self._advance()
                if esc not in escapes:
                    raise MiniSyntaxError(f"unknown escape \\{esc}", self.line, self.col - 2)
                chars.append(escapes[esc])
            else:
                chars.append(ch)
        return Token("STRING", "".join(chars), line, col)


def tokenize(source: str):
    return Lexer(source).tokens()
