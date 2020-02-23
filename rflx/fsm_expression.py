from typing import Callable, Dict, List, Mapping

import z3

from rflx.contract import require
from rflx.error import Location
from rflx.expression import Attribute, Expr, Name, Not, Precedence, Relation, Variable, substitution
from rflx.identifier import ID, StrID


class Valid(Attribute):
    pass


class Present(Attribute):
    pass


class Head(Attribute):
    pass


class Opaque(Attribute):
    pass


class Quantifier(Expr):
    def __init__(
        self, quantifier: StrID, iteratable: Expr, predicate: Expr, location: Location = None
    ) -> None:
        super().__init__(location)
        self.quantifier = ID(quantifier)
        self.iterable = iteratable
        self.predicate = predicate
        self.symbol: str = ""

    def __str__(self) -> str:
        return f"for {self.symbol} {self.quantifier} in {self.iterable} => {self.predicate}"

    def __neg__(self) -> Expr:
        raise NotImplementedError

    @property
    def precedence(self) -> Precedence:
        return Precedence.undefined

    def simplified(self) -> Expr:
        return Quantifier(
            self.quantifier, self.iterable.simplified(), self.predicate.simplified(), self.location,
        )

    @require(lambda func, mapping: (func and mapping is None) or (not func and mapping is not None))
    def substituted(
        self, func: Callable[[Expr], Expr] = None, mapping: Mapping[Name, Expr] = None
    ) -> Expr:
        func = substitution(mapping or {}, func)
        expr = func(self)
        if isinstance(expr, Quantifier):
            return expr.__class__(
                expr.quantifier,
                expr.iterable.substituted(func),
                expr.predicate.substituted(func),
                expr.location,
            )
        return expr

    def z3expr(self) -> z3.ExprRef:
        raise NotImplementedError


class ForSome(Quantifier):
    symbol: str = "some"

    def __neg__(self) -> Expr:
        raise NotImplementedError

    @property
    def precedence(self) -> Precedence:
        return Precedence.undefined

    def z3expr(self) -> z3.ExprRef:
        raise NotImplementedError


class ForAll(Quantifier):
    symbol: str = "all"

    def __neg__(self) -> Expr:
        raise NotImplementedError

    @property
    def precedence(self) -> Precedence:
        return Precedence.undefined

    def z3expr(self) -> z3.ExprRef:
        raise NotImplementedError


class Contains(Relation):
    @property
    def symbol(self) -> str:
        return " in "

    def __neg__(self) -> Expr:
        raise NotImplementedError

    @property
    def precedence(self) -> Precedence:
        return Precedence.undefined

    def z3expr(self) -> z3.ExprRef:
        raise NotImplementedError


class NotContains(Relation):
    @property
    def symbol(self) -> str:
        return " not in "

    def __neg__(self) -> Expr:
        return Not(Contains(self.left, self.right))

    @property
    def precedence(self) -> Precedence:
        return Precedence.undefined

    def z3expr(self) -> z3.ExprRef:
        raise NotImplementedError


class SubprogramCall(Expr):
    def __init__(self, name: StrID, arguments: List[Expr], location: Location = None) -> None:
        super().__init__(location)
        self.name = ID(name)
        self.arguments = arguments

    def __str__(self) -> str:
        arguments = ", ".join([f"{a}" for a in self.arguments])
        return f"{self.name} ({arguments})"

    def __neg__(self) -> Expr:
        raise NotImplementedError

    def simplified(self) -> Expr:
        return SubprogramCall(self.name, [a.simplified() for a in self.arguments], self.location)

    @require(lambda func, mapping: (func and mapping is None) or (not func and mapping is not None))
    def substituted(
        self, func: Callable[[Expr], Expr] = None, mapping: Mapping[Name, Expr] = None
    ) -> Expr:
        func = substitution(mapping or {}, func)
        expr = func(self)
        if isinstance(expr, SubprogramCall):
            return expr.__class__(
                expr.name, [a.substituted(func) for a in expr.arguments], expr.location
            )
        return expr

    @property
    def precedence(self) -> Precedence:
        return Precedence.undefined

    def z3expr(self) -> z3.ExprRef:
        raise NotImplementedError


class Conversion(Expr):
    def __init__(self, name: StrID, argument: Expr, location: Location = None) -> None:
        super().__init__(location)
        self.name = ID(name)
        self.argument = argument

    def __str__(self) -> str:
        return f"{self.name} ({self.argument})"

    def __neg__(self) -> Expr:
        raise NotImplementedError

    @require(lambda func, mapping: (func and mapping is None) or (not func and mapping is not None))
    def substituted(
        self, func: Callable[[Expr], Expr] = None, mapping: Mapping[Name, Expr] = None
    ) -> Expr:
        func = substitution(mapping or {}, func)
        expr = func(self)
        if isinstance(expr, Conversion):
            return expr.__class__(self.name, self.argument.substituted(func))
        return expr

    def simplified(self) -> Expr:
        return Conversion(self.name, self.argument.simplified(), self.location)

    @property
    def precedence(self) -> Precedence:
        raise NotImplementedError

    def z3expr(self) -> z3.ExprRef:
        raise NotImplementedError


class Field(Expr):
    def __init__(self, expression: Expr, field: StrID, location: Location = None) -> None:
        super().__init__(location)
        self.expression = expression
        self.field = ID(field)

    def __str__(self) -> str:
        return f"{self.expression}.{self.field}"

    def __neg__(self) -> Expr:
        raise NotImplementedError

    def simplified(self) -> Expr:
        return Field(self.expression.simplified(), self.field, self.location)

    @require(lambda func, mapping: (func and mapping is None) or (not func and mapping is not None))
    def substituted(
        self, func: Callable[[Expr], Expr] = None, mapping: Mapping[Name, Expr] = None
    ) -> Expr:
        func = substitution(mapping or {}, func)
        expr = func(self)
        if isinstance(expr, Field):
            return expr.__class__(expr.expression.substituted(func), expr.field, expr.location,)
        return expr

    @property
    def precedence(self) -> Precedence:
        return Precedence.undefined

    def z3expr(self) -> z3.ExprRef:
        raise NotImplementedError


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

    def __str__(self) -> str:
        return f"[for {self.iterator} in {self.array} => {self.selector} when {self.condition}]"

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
        if isinstance(expr, Comprehension):
            return expr.__class__(
                expr.iterator,
                expr.array.substituted(func),
                expr.selector.substituted(func),
                expr.condition.substituted(func),
                expr.location,
            )
        return expr

    @property
    def precedence(self) -> Precedence:
        return Precedence.undefined

    def z3expr(self) -> z3.ExprRef:
        raise NotImplementedError


class MessageAggregate(Expr):
    def __init__(self, name: StrID, data: Dict[StrID, Expr], location: Location = None) -> None:
        super().__init__(location)
        self.name = ID(name)
        self.data = {ID(k): v for k, v in data.items()}

    def __str__(self) -> str:
        data = ", ".join([f"{k} => {self.data[k]}" for k in self.data])
        return f"{self.name}'({data})"

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
        if isinstance(expr, MessageAggregate):
            return expr.__class__(
                expr.name, {k: expr.data[k].substituted(func) for k in expr.data}, expr.location,
            )
        return expr

    @property
    def precedence(self) -> Precedence:
        return Precedence.undefined

    def z3expr(self) -> z3.ExprRef:
        raise NotImplementedError


class Binding(Expr):
    def __init__(self, expr: Expr, data: Dict[StrID, Expr], location: Location = None) -> None:
        super().__init__(location)
        self.expr = expr
        self.data = {ID(k): v for k, v in data.items()}

    def __str__(self) -> str:
        data = ", ".join(["{k} = {v}".format(k=k, v=self.data[k]) for k in self.data])
        return f"{self.expr} where {data}"

    def __neg__(self) -> Expr:
        raise NotImplementedError

    def simplified(self) -> Expr:
        facts: Mapping[Name, Expr] = {Variable(k): self.data[k].simplified() for k in self.data}
        return self.expr.substituted(mapping=facts).simplified()

    @require(lambda func, mapping: (func and mapping is None) or (not func and mapping is not None))
    def substituted(
        self, func: Callable[[Expr], Expr] = None, mapping: Mapping[Name, Expr] = None
    ) -> Expr:
        func = substitution(mapping or {}, func)
        expr = func(self)
        if isinstance(expr, Binding):
            return expr.__class__(
                expr.expr, {k: self.data[k].substituted(func) for k in expr.data}, expr.location,
            )
        return expr

    @property
    def precedence(self) -> Precedence:
        return Precedence.undefined

    def z3expr(self) -> z3.ExprRef:
        raise NotImplementedError


class String(Expr):
    def __init__(self, data: str, location: Location = None) -> None:
        super().__init__(location)
        self.data = data

    def __str__(self) -> str:
        return f'"{self.data}"'

    def __neg__(self) -> Expr:
        raise NotImplementedError

    def simplified(self) -> Expr:
        return self

    @require(lambda func, mapping: (func and mapping is None) or (not func and mapping is not None))
    def substituted(
        self, func: Callable[[Expr], Expr] = None, mapping: Mapping[Name, Expr] = None
    ) -> Expr:
        return self

    @property
    def precedence(self) -> Precedence:
        return Precedence.undefined

    def z3expr(self) -> z3.ExprRef:
        raise NotImplementedError
