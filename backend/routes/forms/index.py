"""
Return a list of all forms to authenticated users.
"""

from starlette.responses import JSONResponse

from backend.route import Route


class FormsList(Route):
    """
    List all available forms for administrator viewing.
    """

    name = "forms_list"
    path = "/"

    async def get(self, request):
        forms = []

        for form in request.state.db.forms.find():
            forms.append(form)

        return JSONResponse(
            forms
        )
