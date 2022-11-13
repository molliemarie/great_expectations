from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable, Dict, List, Optional, Type, Union

from typing_extensions import ClassVar

from great_expectations.zep.type_lookup import TypeLookup

if TYPE_CHECKING:
    from great_expectations.data_context import DataContext as GXDataContext
    from great_expectations.execution_engine import ExecutionEngine
    from great_expectations.zep.context import DataContext
    from great_expectations.zep.interfaces import DataAsset, Datasource

SourceFactoryFn = Callable[..., "Datasource"]

LOGGER = logging.getLogger(__name__.lstrip("great_expectations."))


class TypeRegistrationError(TypeError):
    type_: Optional[Type]
    field_name: Optional[str]

    def __init__(
        self,
        message: Union[str, Exception],
        type_: Optional[Type] = None,
        field_name: Optional[str] = None,
    ) -> None:
        self.type = type_
        self.field_name = field_name
        super().__init__(message, type_, field_name)


class _SourceFactories:
    """
    Contains a collection of datasource factory methods in the format `.add_<TYPE_NAME>()`

    Contains a `.type_lookup` dict-like two way mapping between previously registered `Datasource`
    or `DataAsset` types and a simplified name for those types.
    """

    # TODO (kilo59): split DataAsset & Datasource lookups
    type_lookup: ClassVar = TypeLookup()
    engine_lookup: ClassVar = TypeLookup()
    __source_factories: ClassVar[Dict[str, SourceFactoryFn]] = {}

    _data_context: Union[DataContext, GXDataContext]

    def __init__(self, data_context: Union[DataContext, GXDataContext]):
        self._data_context = data_context

    @classmethod
    def register_types_and_ds_factory(
        cls,
        ds_type: Type[Datasource],
        factory_fn: SourceFactoryFn,
    ) -> None:
        """
        Add/Register a datasource factory function and all related `Datasource`,
        `DataAsset` and `ExecutionEngine` types.

        Creates mapping table between the `DataSource`/`DataAsset` classes and their
        declared `type` string.


        Example
        -------

        An `.add_pandas()` pandas factory method will be added to `context.sources`.

        >>> class PandasDatasource(Datasource):
        >>>     type: str = 'pandas'`
        >>>     asset_types = [FileAsset]
        >>>     execution_engine: PandasExecutionEngine
        """

        # TODO: check that the name is a valid python identifier (and maybe that it is snake_case?)
        ds_type_name = ds_type.__fields__["type"].default
        if not ds_type_name:
            raise TypeRegistrationError(
                f"`{ds_type.__name__}` is missing a `type` attribute with an assigned string value"
            )

        # TODO: We should namespace the asset type to the datasource so different datasources can reuse asset types.
        cls._register_assets(ds_type, asset_registrar=cls.type_lookup)

        cls._register_engine(
            ds_type, type_lookup_name=ds_type_name, engine_registrar=cls.engine_lookup
        )

        cls._register_datasource_and_factory_method(
            ds_type,
            factory_fn=factory_fn,
            ds_type_name=ds_type_name,
            datasource_registrar=cls.type_lookup,
        )

    @classmethod
    def _register_datasource_and_factory_method(
        cls,
        ds_type: Type[Datasource],
        factory_fn: SourceFactoryFn,
        ds_type_name: str,
        datasource_registrar: TypeLookup,
    ) -> str:
        """
        Register the `Datasource` class and add a factory method for the class on `sources`.
        The method name is pulled from the `Datasource.type` attribute.
        """
        method_name = f"add_{ds_type_name}"
        LOGGER.info(
            f"2a. Registering {ds_type.__name__} as {ds_type_name} with {method_name}() factory"
        )

        pre_existing = cls.__source_factories.get(method_name)
        if pre_existing:
            raise TypeRegistrationError(
                f"'{ds_type_name}' - `sources.{method_name}()` factory already exists",
                field_name="type",
                type_=ds_type,
            )

        datasource_registrar[ds_type] = ds_type_name
        LOGGER.info(f"'{ds_type_name}' added to `type_lookup`")
        cls.__source_factories[method_name] = factory_fn
        return ds_type_name

    @classmethod
    def _register_engine(
        cls,
        ds_type: Type[Datasource],
        type_lookup_name: str,
        engine_registrar: TypeLookup,
    ):
        try:
            exec_engine_type: Type[ExecutionEngine] = ds_type.__fields__[
                "execution_engine"
            ].type_
        except (AttributeError, KeyError) as exc:
            LOGGER.warning(f"{exc.__class__.__name__}:{exc}")
            raise TypeError(
                f"No `execution_engine` found for {ds_type.__name__} unable to register `ExecutionEngine` type"
            ) from exc

        eng_class_name: str = exec_engine_type.__name__
        if eng_class_name == "ExecutionEngine":
            raise TypeRegistrationError(
                f"`{ds_type.__name__}.execution_engine` must be annotated with a concrete `ExecutionEngine`",
                type_=ds_type,
                field_name="execution_engine",
            )

        LOGGER.info(
            f"2c. Registering `ExecutionEngine` type `{eng_class_name}` for '{type_lookup_name}'"
        )
        engine_registrar[type_lookup_name] = exec_engine_type
        LOGGER.info(list(engine_registrar.keys()))

    @classmethod
    def _register_assets(cls, ds_type: Type[Datasource], asset_registrar: TypeLookup):
        errored_on: Optional[Type[DataAsset]] = None
        try:
            asset_types: List[Type[DataAsset]] = ds_type.asset_types

            if not asset_types:
                LOGGER.warning(
                    f"No `{ds_type.__name__}.asset_types` have be declared for the `Datasource`"
                )

            asset_type_names: List[str] = []
            for t in asset_types:
                try:
                    type_name = t.__fields__["type"].default
                    if type_name is None:
                        raise TypeError(
                            f"{t.__name__} `type` field must be assigned and cannot be `None`"
                        )
                    asset_type_names.append(type_name)
                except (AttributeError, KeyError, TypeError) as bad_field_exc:
                    errored_on = t
                    LOGGER.warning(
                        f"{bad_field_exc.__class__.__name__}:{bad_field_exc}"
                    )
                    raise TypeError(
                        f"No `type` field found for `{ds_type.__name__}.asset_types` -> `{t.__name__}` unable to register asset type"
                    ) from bad_field_exc

            LOGGER.info(f"2b. Registering `DataAsset` types: {asset_type_names}")

            # TODO (kilo59): TypeLookup could support a transaction to prevent 2 loops in this method
            # transaction rollback key additions if conflict occurs
            asset_registrar.raise_if_contains([*asset_types, *asset_type_names])

            for type_, asset_type_name in zip(asset_types, asset_type_names):
                asset_registrar[type_] = asset_type_name
                LOGGER.debug(f"'{asset_type_name}' added to `type_lookup`")
        except TypeError as exc:
            raise TypeRegistrationError(
                exc, type_=errored_on, field_name="asset_types"
            ) from exc

    @property
    def factories(self) -> List[str]:
        return list(self.__source_factories.keys())

    def __getattr__(self, attr_name: str):
        try:
            ds_constructor = self.__source_factories[attr_name]

            def wrapped(name: str, **kwargs):
                datasource = ds_constructor(name=name, **kwargs)
                # TODO (bdirks): _attach_datasource_to_context to the AbstractDataContext class
                self._data_context._attach_datasource_to_context(datasource)  # type: ignore[union-attr]
                return datasource

            return wrapped
        except KeyError:
            raise AttributeError(f"No factory {attr_name} in {self.factories}")

    def __dir__(self) -> List[str]:
        """Preserves autocompletion for dynamic attributes."""
        return [*self.factories, *super().__dir__()]
