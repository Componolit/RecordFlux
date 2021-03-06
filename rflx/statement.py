from abc import abstractmethod
from typing import Callable, Sequence

import rflx.typing_ as rty
from rflx.common import Base
from rflx.error import Location, RecordFluxError, Severity, Subsystem
from rflx.expression import Expr, Variable
from rflx.identifier import ID, StrID


class Statement(Base):
    def __init__(self, identifier: StrID, location: Location = None):
        self.identifier = ID(identifier)
        self.location = location

    @abstractmethod
    def check_type(
        self, statement_type: rty.Type, typify_variable: Callable[[Expr], Expr]
    ) -> RecordFluxError:
        """Set the types of variables, and check the types of the statement and expressions."""
        raise NotImplementedError

    @abstractmethod
    def variables(self) -> Sequence[Variable]:
        raise NotImplementedError


class Assignment(Statement):
    def __init__(self, identifier: StrID, expression: Expr, location: Location = None) -> None:
        super().__init__(identifier, location)
        self.expression = expression

    def __str__(self) -> str:
        return f"{self.identifier} := {self.expression}"

    def check_type(
        self, statement_type: rty.Type, typify_variable: Callable[[Expr], Expr]
    ) -> RecordFluxError:
        self.expression = self.expression.substituted(typify_variable)
        return rty.check_type_instance(
            statement_type, rty.Any, self.location, f'variable "{self.identifier}"'
        ) + self.expression.check_type(statement_type)

    def variables(self) -> Sequence[Variable]:
        return [Variable(self.identifier), *self.expression.variables()]


class AttributeStatement(Statement):
    def __init__(
        self,
        identifier: StrID,
        attribute: str,
        parameters: Sequence[Expr],
        location: Location = None,
    ) -> None:
        super().__init__(identifier, location)
        self.attribute = attribute
        self.parameters = parameters

    def __str__(self) -> str:
        parameters = ", ".join([str(p) for p in self.parameters])
        return f"{self.identifier}'{self.attribute}" + (f" ({parameters})" if parameters else "")

    def check_type(
        self, statement_type: rty.Type, typify_variable: Callable[[Expr], Expr]
    ) -> RecordFluxError:
        raise NotImplementedError

    def variables(self) -> Sequence[Variable]:
        return [Variable(self.identifier), *[e for p in self.parameters for e in p.variables()]]


class ListAttributeStatement(AttributeStatement):
    def __init__(self, identifier: StrID, parameter: Expr, location: Location = None) -> None:
        super().__init__(identifier, self.__class__.__name__, [parameter], location)


class Append(ListAttributeStatement):
    def check_type(
        self, statement_type: rty.Type, typify_variable: Callable[[Expr], Expr]
    ) -> RecordFluxError:
        assert isinstance(self.parameters, list)
        self.parameters[0] = self.parameters[0].substituted(typify_variable)
        error = rty.check_type_instance(
            statement_type, rty.Array, self.location, f'variable "{self.identifier}"'
        )
        if isinstance(statement_type, rty.Array):
            error += self.parameters[0].check_type(statement_type.element)
            if isinstance(statement_type.element, rty.Message) and isinstance(
                self.parameters[0], Variable
            ):
                error.append(
                    "appending independently created message not supported",
                    Subsystem.MODEL,
                    Severity.ERROR,
                    self.parameters[0].location,
                )
                error.append(
                    "message aggregate should be used instead",
                    Subsystem.MODEL,
                    Severity.INFO,
                    self.parameters[0].location,
                )
        return error


class Extend(ListAttributeStatement):
    def check_type(
        self, statement_type: rty.Type, typify_variable: Callable[[Expr], Expr]
    ) -> RecordFluxError:
        assert isinstance(self.parameters, list)
        self.parameters[0] = self.parameters[0].substituted(typify_variable)
        return rty.check_type_instance(
            statement_type, rty.Array, self.location, f'variable "{self.identifier}"'
        ) + self.parameters[0].check_type(statement_type)


class Reset(AttributeStatement):
    def __init__(self, identifier: StrID, location: Location = None) -> None:
        super().__init__(identifier, self.__class__.__name__, [], location)

    def check_type(
        self, statement_type: rty.Type, typify_variable: Callable[[Expr], Expr]
    ) -> RecordFluxError:
        return rty.check_type_instance(
            statement_type,
            (rty.Array, rty.Message),
            self.location,
            f'variable "{self.identifier}"',
        )

    def variables(self) -> Sequence[Variable]:
        return [Variable(self.identifier)]


class ChannelAttributeStatement(AttributeStatement):
    def __init__(self, identifier: StrID, parameter: Expr, location: Location = None) -> None:
        super().__init__(identifier, self.__class__.__name__, [parameter], location)

    def check_type(
        self, statement_type: rty.Type, typify_variable: Callable[[Expr], Expr]
    ) -> RecordFluxError:
        self.parameters = [self.parameters[0].substituted(typify_variable)]
        return (
            rty.check_type(
                statement_type,
                self._expected_channel_type(),
                self.location,
                f'channel "{self.identifier}"',
            )
            + self.parameters[0].check_type_instance(rty.Message)
        )

    @abstractmethod
    def _expected_channel_type(self) -> rty.Channel:
        raise NotImplementedError


class Read(ChannelAttributeStatement):
    def _expected_channel_type(self) -> rty.Channel:
        return rty.Channel(readable=True, writable=False)


class Write(ChannelAttributeStatement):
    def _expected_channel_type(self) -> rty.Channel:
        return rty.Channel(readable=False, writable=True)
