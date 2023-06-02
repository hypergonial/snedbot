import typing as t
from fractions import Fraction

__slots__ = ("Solver", "InvalidExpressionError")

CallableT = t.TypeVar("CallableT", bound=t.Callable[..., Fraction])


class InvalidExpressionError(Exception):
    """Raised when an expression is invalid."""


class Operator(t.Generic[CallableT]):
    """Represents some kind of operator."""

    __slots__ = ("char", "op", "prec")

    def __init__(self, char: str, prec: int, op: CallableT):
        self.char = char
        self.op = op
        self.prec = prec


class UnaryOperator(Operator[t.Callable[[Fraction], Fraction]]):
    """Represents a unary operator."""

    def __call__(self, a: Fraction) -> Fraction:
        return self.op(a)


class BinaryOperator(Operator[t.Callable[[Fraction, Fraction], Fraction]]):
    """Represents a binary operator."""

    def __call__(self, a: Fraction, b: Fraction) -> Fraction:
        return self.op(a, b)


# Workaround because of needed error handling
def _divide(a: Fraction, b: Fraction) -> Fraction:
    try:
        return a / b
    except ZeroDivisionError:
        raise InvalidExpressionError("Division by zero")


OPS: t.Dict[str, Operator] = {
    "+": BinaryOperator("+", 0, lambda a, b: a + b),
    "-": BinaryOperator("-", 0, lambda a, b: a - b),
    "*": BinaryOperator("*", 1, lambda a, b: a * b),
    "/": BinaryOperator("/", 1, _divide),
    "~": UnaryOperator("~", 2, lambda a: -a),
    "^": BinaryOperator("^", 3, lambda a, b: Fraction(a**b)),
}
"""All valid operators."""

VALID_CHARS = set("0123456789.()+-*/^")
"""All valid characters."""


class Solver:
    """Solves arbitrary mathematical expressions using reverse polish notation (RPN)."""

    __slots__ = ("_expr", "_rpn")

    def __init__(self, expr: str):
        self._expr = expr
        self._rpn: t.List[str] = []

    @property
    def expr(self) -> str:
        """The expression to evaluate."""
        return self._expr

    def _validate(self) -> bool:
        """Validates the expression.
        This includes checking for invalid characters and parentheses.

        Returns
        -------
        bool
            Whether the expression is valid.

        Raises
        ------
        InvalidExpressionError
            If the expression is invalid.
        """
        stack = []
        for i, c in enumerate(self._expr):
            if c not in VALID_CHARS:
                raise InvalidExpressionError(f"Illegal character at position {i+1}: {c}")
            if c == "(":
                stack.append(c)
            elif c == ")":
                if not stack:
                    raise InvalidExpressionError(f"Unmatched closing parenthesis at position {i+1}")
                stack.pop()

        if stack:
            raise InvalidExpressionError(f"Unmatched opening parenthesis at position {len(self._expr)}")

        return True

    def _preprocess(self) -> None:
        """Preprocesses the expression.
        This includes adding implicit multiplication signs
        and detecting negations.
        """
        expr = self._expr
        new_expr = []
        for i, c in enumerate(expr):
            if c == "(" and i > 0 and expr[i - 1] not in OPS and expr[i - 1] != "(":
                new_expr.extend(("*", "("))
            elif c == ")" and i + 1 < len(expr) and expr[i + 1] not in OPS and expr[i + 1] not in ("(", ")"):
                new_expr.extend((")", "*"))
            elif c == "-" and (i == 0 or expr[i - 1] in OPS or expr[i - 1] == "("):
                new_expr.append("~")
            else:
                new_expr.append(c)
        self._expr = "".join(new_expr)

    def _should_write_top(self, c: str, stack: t.List[str]) -> bool:
        """Determines if the top operand of the stack should be appended to the result
        before pushing the current operand to the stack.
        This is determined by the precedence of the current operand.

        Parameters
        ----------
        op : str
            The current operand.
        stack : List[str]
            The stack of operands.

        Returns
        -------
        bool
            Whether the top operand should be appended to the result.
        """
        assert c in OPS

        if not stack:
            return False
        top = stack[-1]
        if top == "(":
            return False
        op = OPS[c]
        top_op = OPS[top]
        if c in ["^", "~"] and op.prec >= top_op.prec or op.prec > top_op.prec:
            return False
        return True

    def _to_polish_notation(self) -> None:
        """Convert an expression to polish notation.
        Note that each value must be a single character.

        Parameters
        ----------
        expr : str
            The expression to convert.

        Returns
        -------
        str
            The converted expression.

        Raises
        ------
        InvalidExpressionError
            If the expression is invalid.
        """
        result: t.List[str] = [""]
        stack = []
        for c in self._expr:
            if c.isspace():
                continue

            if c not in OPS and c not in ("(", ")"):
                result[-1] += c
            else:
                if c == "(":
                    stack.append(c)
                elif c == ")":
                    while stack:
                        top = stack.pop()
                        if top == "(":
                            break
                        result.append(top)
                else:
                    while self._should_write_top(c, stack):
                        top = stack.pop()
                        result.append(top)
                    stack.append(c)
                    if not isinstance(OPS[c], UnaryOperator):
                        result.append("")

        result += reversed(stack)

        if "" in result:
            raise InvalidExpressionError("Failed building RPN, invalid expression")

        self._rpn = result

    def solve(self) -> Fraction:
        """Solves the expression.

        Returns
        -------
        Fraction
            The result of the expression.
        """
        self._validate()
        self._preprocess()
        self._to_polish_notation()
        stack = []
        for c in self._rpn:
            if c not in OPS:
                stack.append(Fraction(c))
                continue

            op = OPS[c]
            if isinstance(op, UnaryOperator):
                stack.append(op(stack.pop()))
            elif isinstance(op, BinaryOperator):
                a = stack.pop()
                b = stack.pop()
                stack.append(op(b, a))
        return stack.pop()
