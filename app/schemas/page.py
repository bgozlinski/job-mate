"""One page of a list, and how long the whole list is."""

from pydantic import BaseModel


class Page[Item](BaseModel):
    """
    A page of rows with the count of all of them.

    The total is what lets a client number its pages: without it, the end of a
    list only shows as a page that comes back short.
    """

    items: list[Item]
    total: int
