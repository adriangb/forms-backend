"""
Use a token received from the Discord OAuth2 system to fetch user information.
"""

import datetime
from typing import Union

import httpx
import jwt
from pydantic.fields import Field
from pydantic.main import BaseModel
from spectree.response import Response
from starlette import responses
from starlette.authentication import requires
from starlette.requests import Request

from backend import constants
from backend.authentication.user import User
from backend.constants import SECRET_KEY
from backend.discord import fetch_bearer_token, fetch_user_details
from backend.route import Route
from backend.validation import ErrorMessage, api

AUTH_FAILURE = responses.JSONResponse({"error": "auth_failure"}, status_code=400)


class AuthorizeRequest(BaseModel):
    token: str = Field(description="The access token received from Discord.")


class AuthorizeResponse(BaseModel):
    username: str = Field("Discord display name.")
    expiry: str = Field("ISO formatted timestamp of expiry.")


async def process_token(bearer_token: dict, origin: str) -> Union[AuthorizeResponse, AUTH_FAILURE]:
    """Post a bearer token to Discord, and return a JWT and username."""
    interaction_start = datetime.datetime.now()

    try:
        user_details = await fetch_user_details(bearer_token["access_token"])
    except httpx.HTTPStatusError:
        AUTH_FAILURE.delete_cookie("token")
        return AUTH_FAILURE

    max_age = datetime.timedelta(seconds=int(bearer_token["expires_in"]))
    token_expiry = interaction_start + max_age

    data = {
        "token": bearer_token["access_token"],
        "refresh": bearer_token["refresh_token"],
        "user_details": user_details,
        "expiry": token_expiry.isoformat()
    }

    token = jwt.encode(data, SECRET_KEY, algorithm="HS256")
    user = User(token, user_details)

    response = responses.JSONResponse({
        "username": user.display_name,
        "expiry": token_expiry.isoformat()
    })

    await set_response_token(response, origin, token, bearer_token["expires_in"])
    return response


async def set_response_token(
    response: responses.Response,
    origin_url: str,
    new_token: str,
    expiry: int
) -> None:
    """Helper that handles logic for updating a token in a set-cookie response."""
    if origin_url == constants.PRODUCTION_URL:
        domain = constants.PRODUCTION_URL
        samesite = "strict"

    elif not constants.PRODUCTION:
        domain = None
        samesite = "strict"

    else:
        domain = origin_url
        samesite = "None"

    response.set_cookie(
        "token", f"JWT {new_token}",
        secure=constants.PRODUCTION,
        httponly=True,
        samesite=samesite,
        domain=domain,
        max_age=expiry
    )


class AuthorizeRoute(Route):
    """
    Use the authorization code from Discord to generate a JWT token.
    """

    name = "authorize"
    path = "/authorize"

    @api.validate(
        json=AuthorizeRequest,
        resp=Response(HTTP_200=AuthorizeResponse, HTTP_400=ErrorMessage),
        tags=["auth"]
    )
    async def post(self, request: Request) -> responses.JSONResponse:
        """Generate an authorization token."""
        data = await request.json()
        try:
            url = request.headers.get("origin")
            bearer_token = await fetch_bearer_token(data["token"], url, refresh=False)
        except httpx.HTTPStatusError:
            return AUTH_FAILURE

        return await process_token(bearer_token, url)


class TokenRefreshRoute(Route):
    """
    Use the refresh code from a JWT to get a new token and generate a new JWT token.
    """

    name = "refresh"
    path = "/refresh"

    @requires(["authenticated"])
    @api.validate(
        resp=Response(HTTP_200=AuthorizeResponse, HTTP_400=ErrorMessage),
        tags=["auth"]
    )
    async def post(self, request: Request) -> responses.JSONResponse:
        """Refresh an authorization token."""
        try:
            token = request.user.decoded_token.get("refresh")
            url = request.headers.get("origin")
            bearer_token = await fetch_bearer_token(token, url, refresh=True)
        except httpx.HTTPStatusError:
            return AUTH_FAILURE

        return await process_token(bearer_token, url)
