"""
This module *does not* contain API routes. It exclusively contains dependencies to be used in FastAPI routes
"""
import inspect
from enum import Enum
from string import Template
from typing import (
    Any,
    AsyncGenerator,
    cast,
    NamedTuple,
    Optional,
    Tuple,
    Type,
    TypeVar,
)
from urllib.parse import urlencode

from fastapi import (
    Cookie,
    Form,
    Header,
    Query,
    Request,
    Response,
)
from fastapi.exceptions import RequestValidationError
from fastapi.params import Depends
from fastapi.routing import APIRoute
from fastapi_utils.cbv import cbv
from fastapi_utils.inferring_router import InferringRouter
from pydantic import ValidationError
from pydantic.main import BaseModel
from starlette.datastructures import Headers
from starlette.routing import (
    Match,
    NoMatchFound,
)
from starlette.types import Scope

try:
    from starlette_context import context as request_context
except ImportError:
    request_context = None  # type: ignore[assignment]

from galaxy import app as galaxy_app
from galaxy import (
    model,
    web,
)
from galaxy.exceptions import (
    AdminRequiredException,
    UserCannotRunAsException,
    UserInvalidRunAsException,
)
from galaxy.managers.session import GalaxySessionManager
from galaxy.managers.users import UserManager
from galaxy.model import User
from galaxy.schema.fields import EncodedDatabaseIdField
from galaxy.security.idencoding import IdEncodingHelper
from galaxy.structured_app import StructuredApp
from galaxy.web.framework.decorators import require_admin_message
from galaxy.webapps.base.controller import BaseAPIController
from galaxy.work.context import (
    GalaxyAbstractRequest,
    GalaxyAbstractResponse,
    SessionRequestContext,
)


def get_app() -> StructuredApp:
    return cast(StructuredApp, galaxy_app.app)


async def get_app_with_request_session() -> AsyncGenerator[StructuredApp, None]:
    app = get_app()
    request_id = request_context.data["X-Request-ID"]
    app.model.set_request_id(request_id)
    try:
        yield app
    finally:
        app.model.unset_request_id(request_id)


DependsOnApp = Depends(get_app_with_request_session)


T = TypeVar("T")


class GalaxyTypeDepends(Depends):
    """Variant of fastapi Depends that can also work on WSGI Galaxy controllers."""

    def __init__(self, callable, dep_type):
        super().__init__(callable)
        self.galaxy_type_depends = dep_type


def depends(dep_type: Type[T]) -> T:
    def _do_resolve(request: Request):
        return get_app().resolve(dep_type)

    return cast(T, GalaxyTypeDepends(_do_resolve, dep_type))


def get_session_manager(app: StructuredApp = DependsOnApp) -> GalaxySessionManager:
    # TODO: find out how to adapt dependency for Galaxy/Report/TS
    return GalaxySessionManager(app.model)


def get_session(
    session_manager: GalaxySessionManager = Depends(get_session_manager),
    security: IdEncodingHelper = depends(IdEncodingHelper),
    galaxysession: Optional[str] = Cookie(None),
) -> Optional[model.GalaxySession]:
    if galaxysession:
        session_key = security.decode_guid(galaxysession)
        if session_key:
            return session_manager.get_session_from_session_key(session_key)
        # TODO: What should we do if there is no session? Since this is the API, maybe nothing is the right choice?
    return None


def get_api_user(
    security: IdEncodingHelper = depends(IdEncodingHelper),
    user_manager: UserManager = depends(UserManager),
    key: Optional[str] = Query(None),
    x_api_key: Optional[str] = Header(None),
    run_as: Optional[EncodedDatabaseIdField] = Header(
        default=None,
        title="Run as User",
        description=(
            "The user ID that will be used to effectively make this API call. "
            "Only admins and designated users can make API calls on behalf of other users."
        ),
    ),
) -> Optional[User]:
    api_key = key or x_api_key
    if not api_key:
        return None
    user = user_manager.by_api_key(api_key=api_key)
    if run_as:
        if user_manager.user_can_do_run_as(user):
            try:
                decoded_run_as_id = security.decode_id(run_as)
            except Exception:
                raise UserInvalidRunAsException
            return user_manager.by_id(decoded_run_as_id)
        else:
            raise UserCannotRunAsException
    return user


def get_user(
    galaxy_session: Optional[model.GalaxySession] = Depends(get_session),
    api_user: Optional[User] = Depends(get_api_user),
) -> Optional[User]:
    if galaxy_session:
        return galaxy_session.user
    return api_user


class UrlBuilder:
    def __init__(self, request: Request):
        self.request = request

    def __call__(self, name: str, **path_params):
        qualified = path_params.pop("qualified", False)
        # starlette does not support query parameters in url_path_for: https://github.com/encode/starlette/issues/560
        query_params = path_params.pop("query_params", None)
        try:
            if qualified:
                url = self.request.url_for(name, **path_params)
            else:
                url = self.request.app.url_path_for(name, **path_params)
            if query_params:
                url = f"{url}?{urlencode(query_params)}"
            return url
        except NoMatchFound:
            # Fallback to legacy url_for
            if query_params:
                path_params.update(query_params)
            return web.url_for(name, **path_params)


class GalaxyASGIRequest(GalaxyAbstractRequest):
    """Wrapper around Starlette/FastAPI Request object.

    Implements the GalaxyAbstractRequest interface to provide access to some properties
    of the request commonly used."""

    def __init__(self, request: Request):
        self.__request = request

    @property
    def base(self) -> str:
        return str(self.__request.base_url)

    @property
    def host(self) -> str:
        return str(self.__request.client.host)


class GalaxyASGIResponse(GalaxyAbstractResponse):
    """Wrapper around Starlette/FastAPI Response object.

    Implements the GalaxyAbstractResponse interface to provide access to some properties
    of the response object commonly used."""

    def __init__(self, response: Response):
        self.__response = response

    @property
    def headers(self):
        return self.__response.headers


DependsOnUser = Depends(get_user)


def get_current_history_from_session(galaxy_session: Optional[model.GalaxySession]) -> Optional[model.History]:
    if galaxy_session:
        return galaxy_session.current_history
    return None


def get_trans(
    request: Request,
    response: Response,
    app: StructuredApp = DependsOnApp,
    user: Optional[User] = Depends(get_user),
    galaxy_session: Optional[model.GalaxySession] = Depends(get_session),
) -> SessionRequestContext:
    url_builder = UrlBuilder(request)
    galaxy_request = GalaxyASGIRequest(request)
    galaxy_response = GalaxyASGIResponse(response)
    return SessionRequestContext(
        app=app,
        user=user,
        galaxy_session=galaxy_session,
        url_builder=url_builder,
        request=galaxy_request,
        response=galaxy_response,
        history=get_current_history_from_session(galaxy_session),
    )


DependsOnTrans = Depends(get_trans)


def get_admin_user(trans: SessionRequestContext = DependsOnTrans):
    if not trans.user_is_admin:
        raise AdminRequiredException(require_admin_message(trans.app.config, trans.user))
    return trans.user


AdminUserRequired = Depends(get_admin_user)


class BaseGalaxyAPIController(BaseAPIController):
    def __init__(self, app: StructuredApp):
        super().__init__(app)


class RestVerb(str, Enum):
    get = "GET"
    post = "POST"
    put = "PUT"
    patch = "PATCH"
    delete = "DELETE"
    options = "OPTIONS"


class Router(InferringRouter):
    """A FastAPI Inferring Router tailored to Galaxy."""

    def wrap_with_alias(self, verb: RestVerb, *args, alias: Optional[str] = None, **kwd):
        """
        Wraps FastAPI methods with additional alias keyword and require_admin handling.

        @router.get("/api/thing", alias="/api/deprecated_thing") will then create
        routes for /api/thing and /api/deprecated_thing.
        """
        kwd = self._handle_galaxy_kwd(kwd)

        def decorate_route(route):

            # Decorator solely exists to allow passing `route_class_override` to add_api_route
            def decorated_route(func):
                self.add_api_route(
                    route,
                    endpoint=func,
                    methods=[verb],
                    **kwd,
                )
                return func

            return decorated_route

        route = decorate_route(args[0])

        if alias:
            redecorated_route = decorate_route(alias)

            def dec(f):
                return route(redecorated_route(f))

            return dec
        return route

    def get(self, *args, **kwd):
        """Extend FastAPI.get to accept a require_admin Galaxy flag."""
        return self.wrap_with_alias(RestVerb.get, *args, **kwd)

    def patch(self, *args, **kwd):
        """Extend FastAPI.patch to accept a require_admin Galaxy flag."""
        return self.wrap_with_alias(RestVerb.patch, *args, **kwd)

    def put(self, *args, **kwd):
        """Extend FastAPI.put to accept a require_admin Galaxy flag."""
        return self.wrap_with_alias(RestVerb.put, *args, **kwd)

    def post(self, *args, **kwd):
        """Extend FastAPI.post to accept a require_admin Galaxy flag."""
        return self.wrap_with_alias(RestVerb.post, *args, **kwd)

    def delete(self, *args, **kwd):
        """Extend FastAPI.delete to accept a require_admin Galaxy flag."""
        return self.wrap_with_alias(RestVerb.delete, *args, **kwd)

    def options(self, *args, **kwd):
        return self.wrap_with_alias(RestVerb.options, *args, **kwd)

    def _handle_galaxy_kwd(self, kwd):
        require_admin = kwd.pop("require_admin", False)
        if require_admin:
            if "dependencies" in kwd:
                kwd["dependencies"].append(AdminUserRequired)
            else:
                kwd["dependencies"] = [AdminUserRequired]

        return kwd

    @property
    def cbv(self):
        """Short-hand for frequently used Galaxy-pattern of FastAPI class based views.

        Creates a class-based view for for this router, for more information see:
        https://fastapi-utils.davidmontague.xyz/user-guide/class-based-views/
        """
        return cbv(self)


class APIContentTypeRoute(APIRoute):
    """
    Determines endpoint to match using content-type.
    """

    match_content_type: str

    def accept_matches(self, scope: Scope) -> Tuple[Match, Scope]:
        content_type_header = Headers(scope=scope).get("content-type", None)
        if not content_type_header:
            return Match.PARTIAL, scope
        if self.match_content_type not in content_type_header:
            return Match.NONE, scope
        return Match.FULL, scope

    def matches(self, scope: Scope) -> Tuple[Match, Scope]:
        accept_match, accept_scope = self.accept_matches(scope)
        if accept_match == Match.NONE:
            return accept_match, accept_scope
        match, child_scope = super().matches(accept_scope)
        return (
            match if match.value < accept_match.value else accept_match,
            child_scope,
        )


def as_form(cls: Type[BaseModel]):
    """
    Adds an as_form class method to decorated models. The as_form class method
    can be used with FastAPI endpoints.

    See https://github.com/tiangolo/fastapi/issues/2387#issuecomment-731662551
    """
    new_params = [
        inspect.Parameter(
            field.alias,
            inspect.Parameter.POSITIONAL_ONLY,
            default=(Form(field.default) if not field.required else Form(...)),
        )
        for field in cls.__fields__.values()
    ]

    async def _as_form(**data):
        try:
            return cls(**data)
        except ValidationError as e:
            raise RequestValidationError(e.raw_errors)

    sig = inspect.signature(_as_form)
    sig = sig.replace(parameters=new_params)
    _as_form.__signature__ = sig  # type: ignore[attr-defined]
    cls.as_form = _as_form  # type: ignore[attr-defined]
    return cls


async def try_get_request_body_as_json(request: Request) -> Optional[Any]:
    """Returns the request body as a JSON object if the content type is JSON."""
    if "application/json" in request.headers.get("content-type", ""):
        body = await request.json()
        return body
    return None


search_description_template = Template(
    """A mix of free text and GitHub-style tags used to filter the index operation.

## Query Structure

GitHub-style filter tags (not be confused with Galaxy tags) are tags of the form
`<tag_name>:<text_no_spaces>` or `<tag_name>:'<text with potential spaces>'`. The tag name
*generally* (but not exclusively) corresponds to the name of an attribute on the model
being indexed (i.e. a column in the database).

If the tag is quoted, the attribute will be filtered exactly. If the tag is unquoted,
generally a partial match will be used to filter the query (i.e. in terms of the implementation
this means the database operation `ILIKE` will typically be used).

Once the tagged filters are extracted from the search query, the remaing text is just
used to search various documented attributes of the object.

## GitHub-style Tags Available

${tags}

## Free Text

Free text search terms will be searched against the following attributes of the
${model_name}s: ${freetext}.

"""
)


class IndexQueryTag(NamedTuple):
    tag: str
    description: str
    alias: Optional[str] = None

    def as_markdown(self):
        desc = self.description
        alias = self.alias
        if alias:
            desc += f" (The tag `{alias}` can be used a short hand alias for this tag to filter on this attribute.)"
        return f"`{self.tag}`\n: {desc}"


def search_query_param(model_name: str, tags: list, free_text_fields: list) -> Optional[str]:
    tags_markdown_str = "\n\n".join([t.as_markdown() for t in tags])
    description = search_description_template.safe_substitute(
        model_name=model_name, tags=tags_markdown_str, freetext=", ".join([f"`{t}`" for t in free_text_fields])
    )
    return Query(
        default=None,
        title="Search query.",
        description=description,
    )
