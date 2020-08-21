# pylint: disable=too-many-lines,too-many-ancestors
import itertools
import operator
from abc import ABC, abstractmethod
from enum import Enum
from sys import intern
from typing import Callable, List, Mapping, Optional, Sequence, Tuple, Union

import z3

from rflx.common import generic_repr, indent, indent_next, unique
from rflx.contract import DBC, invariant, require
from rflx.declaration import ChannelDeclaration, Declaration, VariableDeclaration
from rflx.error import Location, RecordFluxError, Severity, Subsystem, fail
from rflx.identifier import ID, StrID


class Precedence(Enum):
    undefined = 0
    boolean_operator = 1
    relational_operator = 2
    binary_adding_operator = 3
    unary_adding_operator = 4
    multiplying_operator = 5
    highest_precedence_operator = 6
    literal = 7


class ProofResult(Enum):
    sat = z3.sat
    unsat = z3.unsat
    unknown = z3.unknown


class Proof:
    def __init__(self, expr: "Expr", facts: Optional[Sequence["Expr"]] = None):
        self.__expr = expr
        self.__facts = facts or []
        self.__result = ProofResult.unsat

        solver = z3.Solver()
        solver.add(self.__expr.z3expr())
        for f in self.__facts:
            solver.add(f.z3expr())

        self.__result = ProofResult(solver.check())

    @property
    def result(self) -> ProofResult:
        return self.__result

    @property
    def error(self) -> List[Tuple[str, Optional[Location]]]:
        assert self.__result == ProofResult.unsat
        solver = z3.Solver()
        solver.set(unsat_core=True)
        facts = {f"H{index}": fact for index, fact in enumerate(self.__facts)}
        for name, fact in facts.items():
            solver.assert_and_track(fact.z3expr(), name)

        solver.assert_and_track(self.__expr.z3expr(), "goal")
        facts["goal"] = self.__expr
        result = solver.check()
        assert result == z3.unsat, f"result should be unsat (is {result})"
        return [
            (" ".join(str(facts[str(fact)]).replace("\n", " ").split()), facts[fact].location)
            for fact in sorted([str(h) for h in solver.unsat_core()])
        ]


class Expr(DBC):
    _str: str

    def __init__(self, location: Location = None):
        self.location = location

    def __eq__(self, other: object) -> bool:
        if isinstance(other, self.__class__):
            return str(self) == str(other)
        return NotImplemented

    def __str__(self) -> str:
        try:
            return self._str
        except AttributeError:
            self._update_str()
            return self._str

    def __hash__(self) -> int:
        return hash(self.__class__.__name__)

    def __repr__(self) -> str:
        return generic_repr(self.__class__.__name__, self.__dict__)

    def __lt__(self, other: object) -> bool:
        if isinstance(other, Expr):
            return False
        return NotImplemented

    def __le__(self, other: object) -> bool:
        if isinstance(other, Expr):
            return self == other
        return NotImplemented

    def __gt__(self, other: object) -> bool:
        if isinstance(other, Expr):
            return False
        return NotImplemented

    def __ge__(self, other: object) -> bool:
        if isinstance(other, Expr):
            return self == other
        return NotImplemented

    def __contains__(self, item: "Expr") -> bool:
        return item == self

    @abstractmethod
    def __neg__(self) -> "Expr":
        raise NotImplementedError

    @abstractmethod
    def _update_str(self) -> None:
        raise NotImplementedError

    @property
    @abstractmethod
    def precedence(self) -> Precedence:
        raise NotImplementedError

    # pylint: disable=no-self-use
    def variables(self) -> List["Variable"]:
        return []

    def findall(self, match: Callable[["Expr"], bool]) -> Sequence["Expr"]:
        return [self] if match(self) else []

    @require(lambda func, mapping: (func and mapping is None) or (not func and mapping is not None))
    def substituted(
        self, func: Callable[["Expr"], "Expr"] = None, mapping: Mapping["Name", "Expr"] = None
    ) -> "Expr":
        func = substitution(mapping or {}, func)
        return func(self)

    @abstractmethod
    def simplified(self) -> "Expr":
        raise NotImplementedError

    def parenthesized(self, expr: "Expr") -> str:
        if expr.precedence.value <= self.precedence.value:
            return "(" + indent_next(str(expr), 1) + ")"
        return str(expr)

    @abstractmethod
    def z3expr(self) -> z3.ExprRef:
        raise NotImplementedError

    def check(self, facts: Optional[Sequence["Expr"]] = None) -> Proof:
        return Proof(self, facts)

    @abstractmethod
    def validate(self, declarations: Mapping[ID, Declaration]) -> None:
        raise NotImplementedError


class BooleanLiteral(Expr):
    _str: str

    def __init__(self, location: Location = None) -> None:
        super().__init__(location)
        self._update_str()

    @abstractmethod
    def __neg__(self) -> "Expr":
        raise NotImplementedError

    @property
    def precedence(self) -> Precedence:
        return Precedence.literal

    def simplified(self) -> Expr:
        return self

    def validate(self, declarations: Mapping[ID, Declaration]) -> None:
        pass


class BooleanTrue(BooleanLiteral):
    def _update_str(self) -> None:
        self._str = intern("True")

    def __repr__(self) -> str:
        return "TRUE"

    def __neg__(self) -> Expr:
        return FALSE

    def z3expr(self) -> z3.BoolRef:
        return z3.BoolVal(True)


TRUE = BooleanTrue()


class BooleanFalse(BooleanLiteral):
    def _update_str(self) -> None:
        self._str = intern("False")

    def __repr__(self) -> str:
        return "FALSE"

    def __neg__(self) -> Expr:
        return TRUE

    def z3expr(self) -> z3.BoolRef:
        return z3.BoolVal(False)


FALSE = BooleanFalse()


class Not(Expr):
    def __init__(self, expr: Expr) -> None:
        super().__init__()
        self.expr = expr

    def _update_str(self) -> None:
        self._str = intern(f"not {self.parenthesized(self.expr)}")

    def __neg__(self) -> Expr:
        return self.expr

    def variables(self) -> List["Variable"]:
        return self.expr.variables()

    @property
    def precedence(self) -> Precedence:
        return Precedence.highest_precedence_operator

    def simplified(self) -> Expr:
        for relation, inverse_relation in [
            (Less, GreaterEqual),
            (LessEqual, Greater),
            (Equal, NotEqual),
            (GreaterEqual, Less),
            (Greater, LessEqual),
            (NotEqual, Equal),
        ]:
            if isinstance(self.expr, relation):
                return inverse_relation(self.expr.left.simplified(), self.expr.right.simplified())
        return self.__class__(self.expr.simplified())

    def z3expr(self) -> z3.BoolRef:
        z3expr = self.expr.z3expr()
        if isinstance(z3expr, z3.BoolRef):
            return z3.Not(z3expr)
        raise TypeError

    def validate(self, declarations: Mapping[ID, Declaration]) -> None:
        self.expr.validate(declarations)


class BinExpr(Expr):
    def __init__(self, left: Expr, right: Expr, location: Location = None) -> None:
        super().__init__(location)
        self.left = left
        self.right = right

    def __repr__(self) -> str:
        return (
            f"\n{self.__class__.__name__}(\n"
            + ",\n".join(indent(repr(t), 4) for t in [self.left, self.right])
            + ")"
        )

    def _update_str(self) -> None:
        self._str = intern(
            f"{self.parenthesized(self.left)}{self.symbol}{self.parenthesized(self.right)}"
        )

    def __neg__(self) -> Expr:
        return self.__class__(-self.left, self.right)

    def __contains__(self, item: Expr) -> bool:
        return item == self or item in (self.left, self.right)

    @property
    @abstractmethod
    def precedence(self) -> Precedence:
        raise NotImplementedError

    def variables(self) -> List["Variable"]:
        return list(unique(self.left.variables() + self.right.variables()))

    def findall(self, match: Callable[["Expr"], bool]) -> Sequence["Expr"]:
        return [
            *([self] if match(self) else []),
            *self.left.findall(match),
            *self.right.findall(match),
        ]

    def substituted(
        self, func: Callable[[Expr], Expr] = None, mapping: Mapping["Name", Expr] = None
    ) -> Expr:
        func = substitution(mapping or {}, func)
        expr = func(self)
        if isinstance(expr, BinExpr):
            return expr.__class__(expr.left.substituted(func), expr.right.substituted(func))
        return expr

    def simplified(self) -> Expr:
        return self.__class__(self.left.simplified(), self.right.simplified())

    def validate(self, declarations: Mapping[ID, Declaration]) -> None:
        self.left.validate(declarations)
        self.right.validate(declarations)

    @property
    @abstractmethod
    def symbol(self) -> str:
        raise NotImplementedError


class AssExpr(Expr):
    def __init__(self, *terms: Expr, location: Location = None) -> None:
        super().__init__(location)
        self.terms = list(terms)

    def __repr__(self) -> str:
        return (
            f"\n{self.__class__.__name__}(\n"
            + ",\n".join(indent(repr(t), 4) for t in self.terms)
            + ")"
        )

    def _update_str(self) -> None:
        self._str = intern(
            self.symbol.join(map(self.parenthesized, self.terms))
            if self.terms
            else str(self.neutral_element())
        )

    @abstractmethod
    def __neg__(self) -> Expr:
        raise NotImplementedError

    def __contains__(self, item: Expr) -> bool:
        return item == self or any(item in term for term in self.terms)

    def __lt__(self, other: object) -> bool:
        if isinstance(other, AssExpr):
            if len(self.terms) == len(other.terms):
                lt = [x < y for x, y in zip(self.terms, other.terms)]
                eq = [x == y for x, y in zip(self.terms, other.terms)]
                return any(lt) and all(map((lambda x: x[0] or x[1]), zip(lt, eq)))
            return False
        return NotImplemented

    def __le__(self, other: object) -> bool:
        if isinstance(other, AssExpr):
            if len(self.terms) == len(other.terms):
                return all([x <= y for x, y in zip(self.terms, other.terms)])
            return False
        return NotImplemented

    def __gt__(self, other: object) -> bool:
        if isinstance(other, AssExpr):
            if len(self.terms) == len(other.terms):
                gt = [x > y for x, y in zip(self.terms, other.terms)]
                eq = [x == y for x, y in zip(self.terms, other.terms)]
                return any(gt) and all(map((lambda x: x[0] or x[1]), zip(gt, eq)))
            return False
        return NotImplemented

    def __ge__(self, other: object) -> bool:
        if isinstance(other, AssExpr):
            if len(self.terms) == len(other.terms):
                return all([x >= y for x, y in zip(self.terms, other.terms)])
            return False
        return NotImplemented

    @property
    @abstractmethod
    def precedence(self) -> Precedence:
        raise NotImplementedError

    def variables(self) -> List["Variable"]:
        return list(unique([v for t in self.terms for v in t.variables()]))

    def findall(self, match: Callable[["Expr"], bool]) -> Sequence["Expr"]:
        return [
            *([self] if match(self) else []),
            *[m for t in self.terms for m in t.findall(match)],
        ]

    def substituted(
        self, func: Callable[[Expr], Expr] = None, mapping: Mapping["Name", Expr] = None
    ) -> Expr:
        func = substitution(mapping or {}, func)
        expr = func(self)
        if isinstance(expr, AssExpr):
            return expr.__class__(*[t.substituted(func) for t in expr.terms])
        return expr

    def simplified(self) -> Expr:
        terms: List[Expr] = []
        all_terms = list(self.terms)
        total = self.neutral_element()
        for term in all_terms:
            t = term.simplified()
            if isinstance(t, Number):
                total = self.operation(total, t.value)
            elif isinstance(t, BooleanTrue):
                total = self.operation(total, 1)
            elif isinstance(t, BooleanFalse):
                total = self.operation(total, 0)
            elif isinstance(t, type(self)):
                all_terms += t.terms
            else:
                terms.append(t)
        boolean = isinstance(self, (And, Or))
        if not terms:
            if boolean:
                return TRUE if total else FALSE
            return Number(total)
        if total != self.neutral_element():
            if boolean:
                terms.append(TRUE if total else FALSE)
            else:
                terms.append(Number(total))
        if len(terms) == 1:
            return terms[0]
        return self.__class__(*terms, location=self.location)

    def validate(self, declarations: Mapping[ID, Declaration]) -> None:
        for term in self.terms:
            term.validate(declarations)

    @abstractmethod
    def operation(self, left: int, right: int) -> int:
        raise NotImplementedError

    @abstractmethod
    def neutral_element(self) -> int:
        raise NotImplementedError

    @property
    @abstractmethod
    def symbol(self) -> str:
        raise NotImplementedError


class BoolAssExpr(AssExpr):
    def _update_str(self) -> None:
        if not self.terms:
            self._str = str(TRUE)
            return
        self._str = ""
        for i, t in reversed(list(enumerate(self.terms))):
            if i == 0:
                self._str = self.parenthesized(t) + self._str
            else:
                self._str = (
                    "\n"
                    + str(self.symbol)[1:]
                    + indent_next(self.parenthesized(t), len(self.symbol) - 1)
                    + self._str
                )
        self._str = intern(self._str)

    @abstractmethod
    def operation(self, left: int, right: int) -> int:
        raise NotImplementedError

    @abstractmethod
    def neutral_element(self) -> int:
        raise NotImplementedError

    @property
    @abstractmethod
    def symbol(self) -> str:
        raise NotImplementedError


class And(BoolAssExpr):
    def __neg__(self) -> Expr:
        return And(*[-term for term in self.terms])

    @property
    def precedence(self) -> Precedence:
        return Precedence.boolean_operator

    def simplified(self) -> Expr:
        simplified_expr = super().simplified()
        if isinstance(simplified_expr, And) and FALSE in simplified_expr.terms:
            return FALSE
        return simplified_expr

    def operation(self, left: int, right: int) -> int:
        return left and right

    def neutral_element(self) -> int:
        return 1

    @property
    def symbol(self) -> str:
        return " and "

    def z3expr(self) -> z3.BoolRef:
        z3exprs = [t.z3expr() for t in self.terms]
        boolexprs = [t for t in z3exprs if isinstance(t, z3.BoolRef)]
        assert len(z3exprs) == len(boolexprs)
        return z3.And(*boolexprs)


class AndThen(And):
    @property
    def symbol(self) -> str:
        return " and then "


class Or(BoolAssExpr):
    def __neg__(self) -> Expr:
        return Or(*[-term for term in self.terms])

    @property
    def precedence(self) -> Precedence:
        return Precedence.boolean_operator

    def simplified(self) -> Expr:
        simplified_expr = super().simplified()
        if isinstance(simplified_expr, Or) and TRUE in simplified_expr.terms:
            return TRUE
        return simplified_expr

    def operation(self, left: int, right: int) -> int:
        return left or right

    def neutral_element(self) -> int:
        return 0

    @property
    def symbol(self) -> str:
        return " or "

    def z3expr(self) -> z3.BoolRef:
        z3exprs = [t.z3expr() for t in self.terms]
        boolexprs = [t for t in z3exprs if isinstance(t, z3.BoolRef)]
        assert len(z3exprs) == len(boolexprs)
        return z3.Or(*boolexprs)


class OrElse(And):
    @property
    def symbol(self) -> str:
        return " or else "


class Number(Expr):
    def __init__(self, value: int, base: int = 0, location: Location = None) -> None:
        super().__init__(location)
        self.value = value
        self.base = base

    def _update_str(self) -> None:
        value = self.value if self.value >= 0 else -self.value
        if self.base == 0:
            self._str = "{}".format(value)
        elif self.base == 2:
            self._str = "2#{:b}#".format(value)
        elif self.base == 8:
            self._str = "8#{:o}#".format(value)
        elif self.base == 10:
            self._str = "10#{}#".format(value)
        elif self.base == 16:
            self._str = "16#{:X}#".format(value)
        else:
            raise NotImplementedError(f"unsupported base {self.base}")
        self._str = intern(f"(-{self._str})" if self.value < 0 else self._str)

    def __hash__(self) -> int:
        return hash(self.value)

    def __int__(self) -> int:
        return self.value

    def __neg__(self) -> "Number":
        return Number(-self.value)

    def __add__(self, other: object) -> "Number":
        if isinstance(other, Number):
            return Number(self.value + other.value)
        return NotImplemented

    def __sub__(self, other: object) -> "Number":
        if isinstance(other, Number):
            return Number(self.value - other.value)
        return NotImplemented

    def __mul__(self, other: object) -> "Number":
        if isinstance(other, Number):
            return Number(self.value * other.value)
        return NotImplemented

    def __floordiv__(self, other: object) -> Expr:
        if isinstance(other, Number):
            if self.value % other.value == 0:
                return Number(self.value // other.value)
            return Div(Number(self.value), Number(other.value))
        return NotImplemented

    def __pow__(self, other: object) -> "Number":
        if isinstance(other, Number):
            return Number(self.value ** other.value)
        return NotImplemented

    def __mod__(self, other: object) -> "Number":
        if isinstance(other, Number):
            return Number(self.value % other.value)
        return NotImplemented

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Number):
            return self.value == other.value
        if isinstance(other, Expr):
            return False
        return NotImplemented

    def __lt__(self, other: object) -> bool:
        if isinstance(other, Number):
            return self.value < other.value
        if isinstance(other, Expr):
            return False
        return NotImplemented

    def __le__(self, other: object) -> bool:
        if isinstance(other, Number):
            return self.value <= other.value
        if isinstance(other, Expr):
            return False
        return NotImplemented

    def __gt__(self, other: object) -> bool:
        if isinstance(other, Number):
            return self.value > other.value
        if isinstance(other, Expr):
            return False
        return NotImplemented

    def __ge__(self, other: object) -> bool:
        if isinstance(other, Number):
            return self.value >= other.value
        if isinstance(other, Expr):
            return False
        return NotImplemented

    @property
    def precedence(self) -> Precedence:
        return Precedence.literal

    def simplified(self) -> Expr:
        return self

    def z3expr(self) -> z3.ArithRef:
        return z3.IntVal(self.value)

    def validate(self, declarations: Mapping[ID, Declaration]) -> None:
        pass


class Add(AssExpr):
    def _update_str(self) -> None:
        if not self.terms:
            self._str = intern(str(self.neutral_element()))
            return
        self._str = str(self.terms[0])
        for t in self.terms[1:]:
            if (isinstance(t, Number) and t.value < 0) or (isinstance(t, Name) and t.negative):
                self._str += f" - {self.parenthesized(-t)}"
            else:
                self._str += f"{self.symbol}{self.parenthesized(t)}"
        self._str = intern(self._str)

    def __neg__(self) -> Expr:
        return Add(*[-term for term in self.terms])

    @property
    def precedence(self) -> Precedence:
        return Precedence.binary_adding_operator

    def operation(self, left: int, right: int) -> int:
        return left + right

    def simplified(self) -> Expr:
        expr = super().simplified()
        if not isinstance(expr, Add):
            return expr
        terms: List[Expr] = []
        for term in reversed(expr.terms):
            complement = False
            for other in terms:
                if other == -term:
                    terms.remove(other)
                    complement = True
                    break
            if not complement:
                terms.insert(0, term)
        if len(terms) == 1:
            return terms[0]
        return Add(*terms, location=self.location)

    def neutral_element(self) -> int:
        return 0

    @property
    def symbol(self) -> str:
        return " + "

    def z3expr(self) -> z3.ArithRef:
        z3expr = sum(t.z3expr() for t in self.terms)
        assert isinstance(z3expr, z3.ArithRef)
        return z3expr


class Mul(AssExpr):
    def __neg__(self) -> Expr:
        return Mul(*list(self.terms) + [Number(-1)]).simplified()

    @property
    def precedence(self) -> Precedence:
        return Precedence.multiplying_operator

    def operation(self, left: int, right: int) -> int:
        return left * right

    def neutral_element(self) -> int:
        return 1

    @property
    def symbol(self) -> str:
        return " * "

    def z3expr(self) -> z3.ArithRef:
        z3expr = self.terms[0].z3expr()
        for t in self.terms[1:]:
            tmp = t.z3expr()
            assert isinstance(z3expr, z3.ArithRef) and isinstance(tmp, z3.ArithRef)
            z3expr = z3expr * tmp
        assert isinstance(z3expr, z3.ArithRef)
        return z3expr


class Sub(BinExpr):
    @property
    def precedence(self) -> Precedence:
        return Precedence.binary_adding_operator

    def simplified(self) -> Expr:
        left = self.left.simplified()
        right = self.right.simplified()
        if isinstance(left, Number) and isinstance(right, Number):
            return left - right
        return Add(left, -right)

    @property
    def symbol(self) -> str:
        return " - "

    def z3expr(self) -> z3.ArithRef:
        left = self.left.z3expr()
        right = self.right.z3expr()
        assert isinstance(left, z3.ArithRef) and isinstance(right, z3.ArithRef)
        return left - right


class Div(BinExpr):
    @property
    def precedence(self) -> Precedence:
        return Precedence.multiplying_operator

    def simplified(self) -> Expr:
        left = self.left.simplified()
        right = self.right.simplified()
        if isinstance(left, Number) and isinstance(right, Number):
            return left // right
        return Div(left, right)

    @property
    def symbol(self) -> str:
        return " / "

    def z3expr(self) -> z3.ArithRef:
        left = self.left.z3expr()
        right = self.right.z3expr()
        assert isinstance(left, z3.ArithRef) and isinstance(right, z3.ArithRef)
        return left / right


class Pow(BinExpr):
    @property
    def precedence(self) -> Precedence:
        return Precedence.highest_precedence_operator

    def simplified(self) -> Expr:
        left = self.left.simplified()
        right = self.right.simplified()
        if isinstance(left, Number) and isinstance(right, Number):
            return left ** right
        return Pow(left, right)

    @property
    def symbol(self) -> str:
        return "**"

    def z3expr(self) -> z3.ArithRef:
        left = self.left.z3expr()
        right = self.right.z3expr()
        assert isinstance(left, z3.ArithRef) and isinstance(right, z3.ArithRef)
        return left ** right


class Mod(BinExpr):
    @property
    def precedence(self) -> Precedence:
        return Precedence.multiplying_operator

    def simplified(self) -> Expr:
        left = self.left.simplified()
        right = self.right.simplified()
        if isinstance(left, Number) and isinstance(right, Number):
            return left % right
        return Mod(left, right)

    @property
    def symbol(self) -> str:
        return " mod "

    def z3expr(self) -> z3.ArithRef:
        left = self.left.z3expr()
        right = self.right.z3expr()
        assert isinstance(left, z3.ArithRef) and isinstance(right, z3.ArithRef)
        return left % right


class Name(Expr):
    def __init__(
        self, negative: bool = False, immutable: bool = False, location: Location = None
    ) -> None:
        super().__init__(location)
        self.negative = negative
        self.immutable = immutable
        self._update_str()

    def _update_str(self) -> None:
        self._str = intern(f"(-{self.representation})" if self.negative else self.representation)

    @property
    def precedence(self) -> Precedence:
        return Precedence.literal

    @property
    @abstractmethod
    def representation(self) -> str:
        raise NotImplementedError

    def substituted(
        self, func: Callable[[Expr], Expr] = None, mapping: Mapping["Name", Expr] = None
    ) -> Expr:
        if self.immutable:
            return self
        func = substitution(mapping or {}, func)
        return -func(-self) if self.negative else func(self)

    def simplified(self) -> Expr:
        return self

    def z3expr(self) -> z3.ExprRef:
        raise NotImplementedError


class Variable(Name):
    def __init__(
        self,
        identifier: StrID,
        negative: bool = False,
        immutable: bool = False,
        location: Location = None,
    ) -> None:
        self.identifier = ID(identifier)
        super().__init__(negative, immutable, location)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, self.__class__):
            return self.negative == other.negative and self.identifier == other.identifier
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self.identifier)

    @property
    def name(self) -> str:
        return str(self.identifier)

    def __neg__(self) -> "Variable":
        return self.__class__(self.identifier, not self.negative, self.immutable, self.location)

    @property
    def representation(self) -> str:
        return str(self.name)

    def variables(self) -> List["Variable"]:
        return [self]

    def validate(self, declarations: Mapping[ID, Declaration]) -> None:
        builtin_types = map(ID, ["Boolean", "True", "False"])
        if self.identifier in builtin_types:
            return
        if self.identifier not in declarations:
            fail(
                f'undeclared variable "{self.name}"', Subsystem.MODEL, Severity.ERROR, self.location
            )
        declarations[self.identifier].reference()

    def z3expr(self) -> z3.ArithRef:
        if self.negative:
            return -z3.Int(self.name)
        return z3.Int(self.name)


class Attribute(Name):
    def __init__(self, prefix: Union[StrID, Expr], negative: bool = False) -> None:
        if isinstance(prefix, ID):
            prefix = Variable(prefix, location=prefix.location)
        if isinstance(prefix, str):
            prefix = Variable(prefix)

        self.prefix: Expr = prefix
        super().__init__(negative, location=prefix.location)

    @property
    def representation(self) -> str:
        return f"{self.prefix}'{self.__class__.__name__}"

    def __neg__(self) -> "Attribute":
        return self.__class__(self.prefix, not self.negative)

    def findall(self, match: Callable[["Expr"], bool]) -> Sequence["Expr"]:
        return [self] if match(self) else self.prefix.findall(match)

    def substituted(
        self, func: Callable[[Expr], Expr] = None, mapping: Mapping[Name, Expr] = None
    ) -> Expr:
        func = substitution(mapping or {}, func)
        expr = func(-self if self.negative else self)
        if isinstance(expr, Attribute):
            expr = expr.__class__(expr.prefix.substituted(func))
        return -expr if self.negative else expr

    def simplified(self) -> Expr:
        expr = self.__class__(self.prefix.simplified())
        return -expr if self.negative else expr

    def variables(self) -> List[Variable]:
        if not isinstance(self.prefix, Variable):
            raise TypeError
        return self.prefix.variables()

    def z3expr(self) -> z3.ExprRef:
        if not isinstance(self.prefix, Variable):
            raise TypeError
        return z3.Int(f"{self.prefix}'{self.__class__.__name__}")

    def validate(self, declarations: Mapping[ID, Declaration]) -> None:
        self.prefix.validate(declarations)


class Size(Attribute):
    pass


class Length(Attribute):
    pass


class First(Attribute):
    pass


class Last(Attribute):
    pass


class Range(Attribute):
    pass


class Old(Attribute):
    pass


class Result(Attribute):
    pass


class Constrained(Attribute):
    pass


class ValidChecksum(Attribute):
    def z3expr(self) -> z3.BoolRef:
        return z3.BoolVal(True)

    @property
    def representation(self) -> str:
        return f"{self.prefix}'Valid_Checksum"


class Valid(Attribute):
    pass


class Present(Attribute):
    pass


class Head(Attribute):
    pass


class Opaque(Attribute):
    pass


class AttributeExpression(Attribute, ABC):
    def __init__(
        self, prefix: Union[StrID, Expr], expression: Expr, negative: bool = False
    ) -> None:
        self.expression = expression
        super().__init__(prefix)

    def __neg__(self) -> "AttributeExpression":
        return self.__class__(self.prefix, self.expression, not self.negative)

    def substituted(
        self, func: Callable[[Expr], Expr] = None, mapping: Mapping[Name, Expr] = None
    ) -> Expr:
        func = substitution(mapping or {}, func)
        expr = func(-self if self.negative else self)
        if isinstance(expr, AttributeExpression):
            expr = expr.__class__(expr.prefix.substituted(func), expr.expression.substituted(func))
        return -expr if self.negative else expr

    def simplified(self) -> Expr:
        prefix = self.prefix.simplified()
        return (
            -self.__class__(prefix, self.expression.simplified())
            if self.negative
            else self.__class__(prefix, self.expression.simplified())
        )

    @property
    def representation(self) -> str:
        return f"{self.prefix}'{self.__class__.__name__} ({self.expression})"


class Val(AttributeExpression):
    pass


class Pos(AttributeExpression):
    pass


@invariant(lambda self: len(self.elements) > 0)
class Indexed(Name):
    def __init__(self, prefix: Expr, *elements: Expr, negative: bool = False) -> None:
        self.prefix = prefix
        self.elements = list(elements)
        super().__init__(negative)

    def __neg__(self) -> "Indexed":
        return self.__class__(self.prefix, *self.elements, negative=not self.negative)

    @property
    def representation(self) -> str:
        return f"{self.prefix} (" + ", ".join(map(str, self.elements)) + ")"

    def z3expr(self) -> z3.ExprRef:
        raise NotImplementedError

    def validate(self, declarations: Mapping[ID, Declaration]) -> None:
        raise NotImplementedError


class Selected(Name):
    def __init__(
        self,
        prefix: Expr,
        selector_name: StrID,
        negative: bool = False,
        immutable: bool = False,
        location: Location = None,
    ) -> None:
        self.prefix = prefix
        self.selector_name = ID(selector_name)
        super().__init__(negative, immutable, location)

    def __neg__(self) -> "Selected":
        return self.__class__(self.prefix, self.selector_name, not self.negative)

    @property
    def representation(self) -> str:
        return f"{self.prefix}.{self.selector_name}"

    def z3expr(self) -> z3.ExprRef:
        raise NotImplementedError

    def variables(self) -> List["Variable"]:
        return self.prefix.variables()

    @require(lambda func, mapping: (func and mapping is None) or (not func and mapping is not None))
    def substituted(
        self, func: Callable[[Expr], Expr] = None, mapping: Mapping[Name, Expr] = None
    ) -> Expr:
        func = substitution(mapping or {}, func)
        expr = func(self)
        assert isinstance(expr, Selected)
        return expr.__class__(
            expr.prefix.substituted(func), expr.selector_name, location=expr.location
        )

    def validate(self, declarations: Mapping[ID, Declaration]) -> None:
        self.prefix.validate(declarations)


class Call(Name):
    def __init__(
        self,
        name: StrID,
        args: Sequence[Expr] = None,
        negative: bool = False,
        immutable: bool = False,
        location: Location = None,
    ) -> None:
        self.name = ID(name)
        self.args = args or []
        super().__init__(negative, immutable, location)

    def __neg__(self) -> "Call":
        return self.__class__(self.name, self.args, not self.negative)

    @property
    def representation(self) -> str:
        args = ", ".join(map(str, self.args))
        if args:
            args = f" ({args})"
        call = f"{self.name}{args}"
        return call

    def z3expr(self) -> z3.ExprRef:
        raise NotImplementedError

    def __validate_channel(
        self, declarations: Mapping[ID, Declaration], error: RecordFluxError
    ) -> None:
        if len(self.args) < 1:
            fail(
                f'no channel argument in call to "{self.name}"',
                Subsystem.MODEL,
                Severity.ERROR,
                self.location,
            )
        channel_id = self.args[0]
        if not isinstance(channel_id, Variable):
            fail(
                f'invalid channel ID type in call to "{self.name}"',
                Subsystem.MODEL,
                Severity.ERROR,
                self.location,
            )
        assert isinstance(channel_id, Variable)
        if channel_id.identifier not in declarations:
            fail(
                f'undeclared channel "{channel_id}" in call to "{self.name}"',
                Subsystem.MODEL,
                Severity.ERROR,
                self.location,
            )

        assert isinstance(channel_id, Variable)
        channel = declarations[channel_id.identifier]
        if not isinstance(channel, ChannelDeclaration):
            fail(
                f'invalid channel type in call to "{self.name}"',
                Subsystem.MODEL,
                Severity.ERROR,
                self.location,
            )

        assert isinstance(channel, ChannelDeclaration)
        channel.reference()
        if self.name in map(ID, ["Write", "Call"]) and not channel.writable:
            error.append(
                f'channel "{channel_id}" not writable in call to "{self.name}"',
                Subsystem.MODEL,
                Severity.ERROR,
                self.location,
            )
        if self.name in map(ID, ["Call", "Read", "Data_Available"]) and not channel.readable:
            error.append(
                f'channel "{channel_id}" not readable in call to "{self.name}"',
                Subsystem.MODEL,
                Severity.ERROR,
                self.location,
            )
        for a in self.args[1:]:
            a.validate(declarations)

    def validate(self, declarations: Mapping[ID, Declaration]) -> None:
        error = RecordFluxError()
        if self.name in map(ID, ["Read", "Write", "Call", "Data_Available"]):
            self.__validate_channel(declarations, error)
        else:
            if self.name not in map(ID, ["Append", "Extend"]):
                if self.name not in declarations:
                    fail(
                        f'undeclared subprogram "{self.name}" called',
                        Subsystem.MODEL,
                        Severity.ERROR,
                        self.location,
                    )
                declarations[self.name].reference()
            for a in self.args:
                try:
                    a.validate(declarations)
                except RecordFluxError as e:
                    error.extend(e)
        error.propagate()

    def variables(self) -> List["Variable"]:
        result = []
        for t in self.args:
            result.extend(t.variables())
        return result

    @require(lambda func, mapping: (func and mapping is None) or (not func and mapping is not None))
    def substituted(
        self, func: Callable[[Expr], Expr] = None, mapping: Mapping[Name, Expr] = None
    ) -> Expr:
        func = substitution(mapping or {}, func)
        expr = func(self)
        assert isinstance(expr, Call)
        return expr.__class__(
            expr.name,
            [a.substituted(func) for a in expr.args],
            expr.negative,
            expr.immutable,
            expr.location,
        )


class Slice(Name):
    def __init__(self, prefix: Expr, first: Expr, last: Expr) -> None:
        self.prefix = prefix
        self.first = first
        self.last = last
        super().__init__()

    def __neg__(self) -> "Slice":
        return self

    @property
    def representation(self) -> str:
        return f"{self.prefix} ({self.first} .. {self.last})"

    def substituted(
        self, func: Callable[[Expr], Expr] = None, mapping: Mapping[Name, Expr] = None
    ) -> Expr:
        func = substitution(mapping or {}, func)
        expr = func(self)
        if isinstance(expr, self.__class__):
            return expr.__class__(
                expr.prefix.substituted(func),
                expr.first.substituted(func),
                expr.last.substituted(func),
            )
        return expr

    def simplified(self) -> Expr:
        return self.__class__(
            self.prefix.simplified(), self.first.simplified(), self.last.simplified()
        )

    def z3expr(self) -> z3.ExprRef:
        raise NotImplementedError

    def validate(self, declarations: Mapping[ID, Declaration]) -> None:
        raise NotImplementedError


class UndefinedExpr(Name):
    @property
    def representation(self) -> str:
        return "__UNDEFINED__"

    def __neg__(self) -> "UndefinedExpr":
        raise NotImplementedError

    def z3expr(self) -> z3.ExprRef:
        raise NotImplementedError

    def validate(self, declarations: Mapping[ID, Declaration]) -> None:
        raise NotImplementedError


UNDEFINED = UndefinedExpr()


@invariant(lambda self: len(self.elements) > 0)
class Aggregate(Expr):
    def __init__(self, *elements: Expr, location: Location = None) -> None:
        super().__init__(location)
        self.elements = list(elements)

    def _update_str(self) -> None:
        self._str = intern("(" + ", ".join(map(str, self.elements)) + ")")

    def __neg__(self) -> Expr:
        raise NotImplementedError

    @property
    def precedence(self) -> Precedence:
        return Precedence.literal

    def substituted(
        self, func: Callable[[Expr], Expr] = None, mapping: Mapping[Name, Expr] = None
    ) -> Expr:
        func = substitution(mapping or {}, func)
        expr = func(self)
        if isinstance(expr, self.__class__):
            return expr.__class__(*[e.substituted(func) for e in expr.elements])
        return expr

    def simplified(self) -> Expr:
        return self.__class__(*[e.simplified() for e in self.elements])

    @property
    def length(self) -> Expr:
        return Number(len(self.elements))

    def z3expr(self) -> z3.ExprRef:
        return z3.BoolVal(False)

    def validate(self, declarations: Mapping[ID, Declaration]) -> None:
        raise NotImplementedError


class String(Aggregate):
    def __init__(self, data: str, location: Location = None) -> None:
        super().__init__(*[Number(ord(d)) for d in data], location=location)
        self.data = data

    def _update_str(self) -> None:
        self._str = intern(f'"{self.data}"')

    def __neg__(self) -> Expr:
        raise NotImplementedError

    @property
    def precedence(self) -> Precedence:
        raise NotImplementedError

    def substituted(
        self, func: Callable[[Expr], Expr] = None, mapping: Mapping[Name, Expr] = None
    ) -> Expr:
        func = substitution(mapping or {}, func)
        return func(self)

    def simplified(self) -> Expr:
        return self

    def z3expr(self) -> z3.ExprRef:
        return z3.BoolVal(False)

    def validate(self, declarations: Mapping[ID, Declaration]) -> None:
        pass


class NamedAggregate(Expr):
    def __init__(self, *elements: Tuple[StrID, Expr]) -> None:
        super().__init__()
        self.elements = [(ID(n), e) for n, e in elements]

    def _update_str(self) -> None:
        self._str = intern(
            "(" + ", ".join(f"{name} => {element}" for name, element in self.elements) + ")"
        )

    def __neg__(self) -> Expr:
        raise NotImplementedError

    @property
    def precedence(self) -> Precedence:
        raise NotImplementedError

    def substituted(
        self, func: Callable[[Expr], Expr] = None, mapping: Mapping[Name, Expr] = None
    ) -> Expr:
        func = substitution(mapping or {}, func)
        expr = func(self)
        if isinstance(expr, self.__class__):
            return expr.__class__(*[(n, e.substituted(func)) for n, e in expr.elements])
        return expr

    def simplified(self) -> Expr:
        return self.__class__(*[(n, e.simplified()) for n, e in self.elements])

    def z3expr(self) -> z3.ExprRef:
        raise NotImplementedError

    def validate(self, declarations: Mapping[ID, Declaration]) -> None:
        raise NotImplementedError


class Relation(BinExpr):
    @abstractmethod
    def __neg__(self) -> Expr:
        raise NotImplementedError

    def _simplified(self, relation_operator: Callable[[Number, Number], bool]) -> Expr:
        left = self.left.simplified()
        right = self.right.simplified()
        if relation_operator in [operator.eq, operator.le, operator.ge] and left == right:
            return TRUE
        if isinstance(left, Number) and isinstance(right, Number):
            return TRUE if relation_operator(left, right) else FALSE
        return self.__class__(left, right)

    @property
    def precedence(self) -> Precedence:
        return Precedence.relational_operator


class Less(Relation):
    def __neg__(self) -> Expr:
        return GreaterEqual(self.left, self.right)

    @property
    def symbol(self) -> str:
        return " < "

    def simplified(self) -> Expr:
        return self._simplified(operator.lt)

    def z3expr(self) -> z3.BoolRef:
        left = self.left.z3expr()
        right = self.right.z3expr()
        assert isinstance(left, z3.ArithRef) and isinstance(right, z3.ArithRef)
        return left < right


class LessEqual(Relation):
    def __neg__(self) -> Expr:
        return Greater(self.left, self.right)

    @property
    def symbol(self) -> str:
        return " <= "

    def simplified(self) -> Expr:
        return self._simplified(operator.le)

    def z3expr(self) -> z3.BoolRef:
        left = self.left.z3expr()
        right = self.right.z3expr()
        assert isinstance(left, z3.ArithRef) and isinstance(right, z3.ArithRef)
        return left <= right


class Equal(Relation):
    def __neg__(self) -> Expr:
        return NotEqual(self.left, self.right)

    @property
    def symbol(self) -> str:
        return " = "

    def simplified(self) -> Expr:
        return self._simplified(operator.eq)

    def z3expr(self) -> z3.BoolRef:
        left = self.left.z3expr()
        right = self.right.z3expr()
        result = left == right
        assert isinstance(result, z3.BoolRef)
        return result


class GreaterEqual(Relation):
    def __neg__(self) -> Expr:
        return Less(self.left, self.right)

    @property
    def symbol(self) -> str:
        return " >= "

    def simplified(self) -> Expr:
        return self._simplified(operator.ge)

    def z3expr(self) -> z3.BoolRef:
        left = self.left.z3expr()
        right = self.right.z3expr()
        assert isinstance(left, z3.ArithRef) and isinstance(right, z3.ArithRef)
        return left >= right


class Greater(Relation):
    def __neg__(self) -> Expr:
        return LessEqual(self.left, self.right)

    @property
    def symbol(self) -> str:
        return " > "

    def simplified(self) -> Expr:
        return self._simplified(operator.gt)

    def z3expr(self) -> z3.BoolRef:
        left = self.left.z3expr()
        right = self.right.z3expr()
        assert isinstance(left, z3.ArithRef) and isinstance(right, z3.ArithRef)
        return left > right


class NotEqual(Relation):
    def __neg__(self) -> Expr:
        return Equal(self.left, self.right)

    @property
    def symbol(self) -> str:
        return " /= "

    def simplified(self) -> Expr:
        return self._simplified(operator.ne)

    def z3expr(self) -> z3.BoolRef:
        left = self.left.z3expr()
        right = self.right.z3expr()
        result = left != right
        assert isinstance(result, z3.BoolRef)
        return result


class In(Relation):
    def __neg__(self) -> Expr:
        return NotIn(self.left, self.right)

    @property
    def symbol(self) -> str:
        return " in "

    def z3expr(self) -> z3.BoolRef:
        raise NotImplementedError


class NotIn(Relation):
    def __neg__(self) -> Expr:
        return In(self.left, self.right)

    @property
    def symbol(self) -> str:
        return " not in "

    def z3expr(self) -> z3.BoolRef:
        raise NotImplementedError


class If(Expr):
    def __init__(
        self, condition_expressions: Sequence[Tuple[Expr, Expr]], else_expression: Expr = None
    ) -> None:
        super().__init__()
        self.condition_expressions = condition_expressions
        self.else_expression = else_expression

    def _update_str(self) -> None:
        self._str = ""
        for c, e in self.condition_expressions:
            if not self._str:
                self._str = f"(if\n{indent(str(c), 4)}\n then\n{indent(str(e), 4)}"
            else:
                self._str += f"\n elsif\n{indent(str(c), 4)}\n then\n{indent(str(e), 4)}"
        if self.else_expression:
            self._str += f"\n else\n{indent(str(self.else_expression), 4)}"
        self._str += ")"
        self._str = intern(self._str)

    def __neg__(self) -> Expr:
        raise NotImplementedError

    @property
    def precedence(self) -> Precedence:
        return Precedence.literal

    def findall(self, match: Callable[["Expr"], bool]) -> Sequence["Expr"]:
        return [
            *([self] if match(self) else []),
            *[
                m
                for c, e in self.condition_expressions
                for m in itertools.chain(c.findall(match), e.findall(match))
            ],
        ]

    def substituted(
        self, func: Callable[[Expr], Expr] = None, mapping: Mapping[Name, Expr] = None
    ) -> Expr:
        func = substitution(mapping or {}, func)
        expr = func(self)
        if isinstance(expr, self.__class__):
            return expr.__class__(
                [(c.substituted(func), e.substituted(func)) for c, e in expr.condition_expressions],
                expr.else_expression.substituted(func) if expr.else_expression else None,
            )
        return expr

    def simplified(self) -> Expr:
        simplified_ce = [(c.simplified(), e.simplified()) for c, e in self.condition_expressions]

        if len(simplified_ce) == 1 and simplified_ce[0][0] == TRUE:
            return simplified_ce[0][1]

        return If(simplified_ce, self.else_expression)

    def variables(self) -> List["Variable"]:
        variables = []
        for ce in self.condition_expressions:
            variables.extend(ce[0].variables())
            variables.extend(ce[1].variables())
        if self.else_expression:
            variables.extend(self.else_expression.variables())
        return list(unique(variables))

    def z3expr(self) -> z3.ExprRef:
        return If.ifexpr(self.condition_expressions, self.else_expression)

    @staticmethod
    def ifexpr(conditions: Sequence[Tuple[Expr, Expr]], elseexpr: Optional[Expr]) -> z3.ExprRef:
        if conditions:
            c = conditions[0][0].z3expr()
            e = conditions[0][1].z3expr()
            r = If.ifexpr(conditions[1:], elseexpr)
            assert isinstance(c, z3.BoolRef)
            return z3.If(c, e, r)
        if elseexpr:
            return elseexpr.z3expr()
        return z3.BoolVal(False)

    def validate(self, declarations: Mapping[ID, Declaration]) -> None:
        raise NotImplementedError


class Case(Expr):
    def __init__(
        self, control_expression: Expr, case_statements: Sequence[Tuple[Expr, Expr]]
    ) -> None:
        super().__init__()
        self.control_expression = control_expression
        self.case_statements = case_statements

    def _update_str(self) -> None:
        grouped_cases = [
            (" | ".join(str(c) for c, _ in choices), expr)
            for expr, choices in itertools.groupby(self.case_statements, lambda x: x[1])
        ]
        cases = indent(
            ",".join(
                [f"\nwhen {choice} =>\n{indent(str(expr), 3)}" for choice, expr in grouped_cases]
            ),
            4,
        )
        self._str = intern(f"(case {self.control_expression} is{cases})")

    def __neg__(self) -> Expr:
        raise NotImplementedError

    @property
    def precedence(self) -> Precedence:
        return Precedence.literal

    def substituted(
        self, func: Callable[[Expr], Expr] = None, mapping: Mapping[Name, Expr] = None
    ) -> Expr:
        func = substitution(mapping or {}, func)
        expr = func(self)
        if isinstance(expr, self.__class__):
            return expr.__class__(
                expr.control_expression.substituted(func),
                [(c.substituted(func), e.substituted(func)) for c, e in expr.case_statements],
            )
        return expr

    def simplified(self) -> Expr:
        if len(self.case_statements) == 1 and self.case_statements[0][0] == Variable("others"):
            return self.case_statements[0][1]
        return Case(
            self.control_expression.simplified(),
            [(c.simplified(), e.simplified()) for c, e in self.case_statements],
        )

    def variables(self) -> List["Variable"]:
        variables = self.control_expression.variables()
        for cs in self.case_statements:
            variables.extend(cs[0].variables())
            variables.extend(cs[1].variables())
        return list(unique(variables))

    def z3expr(self) -> Union[z3.BoolRef, z3.ExprRef]:
        return Case.caseexpr(self.control_expression, self.case_statements)

    @staticmethod
    def caseexpr(
        control: Expr, statements: Sequence[Tuple[Expr, Expr]]
    ) -> Union[z3.ExprRef, z3.BoolRef]:
        if statements:
            condition, expression = statements[0]
            return z3.If(
                control.z3expr() == condition.z3expr(),
                expression.z3expr(),
                Case.caseexpr(control, statements[1:]),
            )
        return z3.BoolVal(False)

    def validate(self, declarations: Mapping[ID, Declaration]) -> None:
        raise NotImplementedError


class QuantifiedExpression(Expr):
    def __init__(
        self, parameter_name: StrID, iterable: Expr, predicate: Expr, location: Location = None
    ) -> None:
        super().__init__(location)
        self.parameter_name = ID(parameter_name)
        self.iterable = iterable
        self.predicate = predicate

    def _update_str(self) -> None:
        self._str = intern(
            f"(for {self.quantifier} {self.parameter_name} {self.keyword} {self.iterable} =>\n"
            + indent(str(self.predicate), 4)
            + ")"
        )

    @property
    def precedence(self) -> Precedence:
        return Precedence.literal

    def simplified(self) -> Expr:
        return self.__class__(
            self.parameter_name, self.iterable.simplified(), self.predicate.simplified()
        )

    @property
    @abstractmethod
    def quantifier(self) -> str:
        raise NotImplementedError

    @property
    @abstractmethod
    def keyword(self) -> str:
        raise NotImplementedError

    def variables(self) -> List["Variable"]:
        return list(
            unique(
                v
                for v in self.iterable.variables() + self.predicate.variables()
                if v.identifier != self.parameter_name
            )
        )

    def z3expr(self) -> z3.ExprRef:
        raise NotImplementedError

    @require(lambda func, mapping: (func and mapping is None) or (not func and mapping is not None))
    def substituted(
        self, func: Callable[[Expr], Expr] = None, mapping: Mapping[Name, Expr] = None
    ) -> Expr:
        func = substitution(mapping or {}, func)
        expr = func(self)
        assert isinstance(expr, QuantifiedExpression)
        return expr.__class__(
            expr.parameter_name,
            expr.iterable.substituted(func),
            expr.predicate.substituted(func),
            expr.location,
        )

    def validate(self, declarations: Mapping[ID, Declaration]) -> None:
        quantifier: Mapping[ID, Declaration] = {
            self.parameter_name: VariableDeclaration(self.parameter_name)
        }
        self.iterable.validate({**declarations, **quantifier})
        self.predicate.validate({**declarations, **quantifier})


class ForAllOf(QuantifiedExpression):
    def __neg__(self) -> Expr:
        raise NotImplementedError

    @property
    def quantifier(self) -> str:
        return "all"

    @property
    def keyword(self) -> str:
        return "of"


class ForAllIn(QuantifiedExpression):
    def __neg__(self) -> Expr:
        raise NotImplementedError

    @property
    def quantifier(self) -> str:
        return "all"

    @property
    def keyword(self) -> str:
        return "in"


class ForSomeIn(QuantifiedExpression):
    def __neg__(self) -> Expr:
        raise NotImplementedError

    @property
    def quantifier(self) -> str:
        return "some"

    @property
    def keyword(self) -> str:
        return "in"


class ValueRange(Expr):
    def __init__(self, lower: Expr, upper: Expr, location: Location = None):
        super().__init__(location)
        self.lower = lower
        self.upper = upper

    def _update_str(self) -> None:
        self._str = intern(f"{self.lower} .. {self.upper}")

    def __neg__(self) -> Expr:
        raise NotImplementedError

    @property
    def precedence(self) -> Precedence:
        raise NotImplementedError

    def simplified(self) -> Expr:
        return self.__class__(self.lower.simplified(), self.upper.simplified())

    def z3expr(self) -> z3.ExprRef:
        raise NotImplementedError

    def substituted(
        self, func: Callable[["Expr"], "Expr"] = None, mapping: Mapping["Name", "Expr"] = None
    ) -> "Expr":
        func = substitution(mapping or {}, func)
        expr = func(self)
        if isinstance(expr, self.__class__):
            return self.__class__(self.lower.substituted(func), self.upper.substituted(func),)
        return expr

    def validate(self, declarations: Mapping[ID, Declaration]) -> None:
        raise NotImplementedError


class Conversion(Expr):
    def __init__(self, name: StrID, argument: Expr, location: Location = None) -> None:
        super().__init__(location)
        self.name = ID(name)
        self.argument = argument

    def _update_str(self) -> None:
        self._str = intern(f"{self.name} ({self.argument})")

    def __neg__(self) -> Expr:
        raise NotImplementedError

    @require(lambda func, mapping: (func and mapping is None) or (not func and mapping is not None))
    def substituted(
        self, func: Callable[[Expr], Expr] = None, mapping: Mapping[Name, Expr] = None
    ) -> Expr:
        func = substitution(mapping or {}, func)
        expr = func(self)
        assert isinstance(expr, Conversion)
        return expr.__class__(self.name, self.argument.substituted(func))

    def simplified(self) -> Expr:
        return Conversion(self.name, self.argument.simplified(), self.location)

    @property
    def precedence(self) -> Precedence:
        return Precedence.literal

    def z3expr(self) -> z3.ExprRef:
        raise NotImplementedError

    def validate(self, declarations: Mapping[ID, Declaration]) -> None:
        self.argument.validate(declarations)

    def variables(self) -> List["Variable"]:
        return self.argument.variables()


class Comprehension(Expr):
    def __init__(
        self,
        iterator: StrID,
        array: Expr,
        selector: Expr,
        condition: Expr,
        location: Location = None,
    ) -> None:
        super().__init__(location)
        self.iterator = ID(iterator)
        self.array = array
        self.selector = selector
        self.condition = condition

    def _update_str(self) -> None:
        self._str = intern(
            f"[for {self.iterator} in {self.array} => {self.selector} when {self.condition}]"
        )

    def __neg__(self) -> Expr:
        raise NotImplementedError

    def simplified(self) -> Expr:
        return Comprehension(
            self.iterator,
            self.array.simplified(),
            self.selector.simplified(),
            self.condition.simplified(),
            self.location,
        )

    @require(lambda func, mapping: (func and mapping is None) or (not func and mapping is not None))
    def substituted(
        self, func: Callable[[Expr], Expr] = None, mapping: Mapping[Name, Expr] = None
    ) -> Expr:
        func = substitution(mapping or {}, func)
        expr = func(self)
        assert isinstance(expr, Comprehension)
        return expr.__class__(
            expr.iterator,
            expr.array.substituted(func),
            expr.selector.substituted(func),
            expr.condition.substituted(func),
            expr.location,
        )

    @property
    def precedence(self) -> Precedence:
        raise NotImplementedError

    def z3expr(self) -> z3.ExprRef:
        raise NotImplementedError

    def validate(self, declarations: Mapping[ID, Declaration]) -> None:
        decls: Mapping[ID, Declaration] = {
            **declarations,
            self.iterator: VariableDeclaration(self.iterator),
        }
        self.array.validate(decls)
        self.selector.validate(decls)
        self.condition.validate(decls)

    def variables(self) -> List["Variable"]:
        return [
            v
            for v in self.array.variables() + self.selector.variables() + self.condition.variables()
            if v.identifier != self.iterator
        ]


class MessageAggregate(Expr):
    def __init__(self, name: StrID, data: Mapping[StrID, Expr], location: Location = None) -> None:
        super().__init__(location)
        self.name = ID(name)
        self.data = {ID(k): v for k, v in data.items()}

    def _update_str(self) -> None:
        data = (
            ", ".join(f"{k} => {self.data[k]}" for k in self.data) if self.data else "null message"
        )
        self._str = intern(f"{self.name}'({data})")

    def __neg__(self) -> Expr:
        raise NotImplementedError

    def simplified(self) -> Expr:
        return MessageAggregate(
            self.name, {k: self.data[k].simplified() for k in self.data}, self.location
        )

    @require(lambda func, mapping: (func and mapping is None) or (not func and mapping is not None))
    def substituted(
        self, func: Callable[[Expr], Expr] = None, mapping: Mapping[Name, Expr] = None
    ) -> Expr:
        func = substitution(mapping or {}, func)
        expr = func(self)
        assert isinstance(expr, MessageAggregate)
        return expr.__class__(
            expr.name, {k: expr.data[k].substituted(func) for k in expr.data}, expr.location,
        )

    @property
    def precedence(self) -> Precedence:
        raise NotImplementedError

    def z3expr(self) -> z3.ExprRef:
        raise NotImplementedError

    def validate(self, declarations: Mapping[ID, Declaration]) -> None:
        for k in self.data:
            self.data[k].validate(declarations)

    def variables(self) -> List["Variable"]:
        result = []
        for v in self.data.values():
            result.extend(v.variables())
        return result


class Binding(Expr):
    def __init__(self, expr: Expr, data: Mapping[StrID, Expr], location: Location = None) -> None:
        super().__init__(location)
        self.expr = expr
        self.data = {ID(k): v for k, v in data.items()}

    def _update_str(self) -> None:
        data = ",\n".join("{k} = {v}".format(k=k, v=self.data[k]) for k in self.data)
        self._str = intern(f"{self.expr}\n   where {indent_next(data, 9)}")

    def __neg__(self) -> Expr:
        raise NotImplementedError

    def simplified(self) -> Expr:
        facts: Mapping[Name, Expr] = {Variable(k): self.data[k].simplified() for k in self.data}
        return self.expr.substituted(mapping=facts).simplified()

    def substituted(
        self, func: Callable[[Expr], Expr] = None, mapping: Mapping[Name, Expr] = None
    ) -> Expr:
        raise NotImplementedError

    @property
    def precedence(self) -> Precedence:
        raise NotImplementedError

    def z3expr(self) -> z3.ExprRef:
        raise NotImplementedError

    def variables(self) -> List["Variable"]:
        return self.simplified().variables()

    def validate(self, declarations: Mapping[ID, Declaration]) -> None:
        self.simplified().validate(declarations)


def substitution(
    mapping: Mapping[Name, Expr], func: Callable[["Expr"], "Expr"] = None
) -> Callable[[Expr], Expr]:
    if func:
        return func
    return lambda expression: (
        mapping[expression]
        if isinstance(expression, Name) and expression in mapping
        else expression
    )
