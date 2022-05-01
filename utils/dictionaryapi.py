from __future__ import annotations

import re
import typing as t

import aiohttp
import attr

# The idea for creating this module, along with the URL for the autocomplete endpoint was found here:
# https://github.com/advaith1/dictionary


class DictionaryException(Exception):
    """An exception raised if the connection to the Dictionary API fails."""


@attr.frozen()
class DictionaryEntry:
    id: str
    """The ID of this entry in the dictionary."""

    word: str
    """The word in the dictionary entry."""

    definitions: t.List[str]
    """A list of definitions for the word."""

    offensive: bool
    """Whether the word is offensive."""

    functional_label: t.Optional[str] = None
    """The functional label of the word (e.g. noun)"""

    etymology: t.Optional[str] = None
    """The etymology of the word."""

    date: t.Optional[str] = None
    """An estimated date when the word was first used."""

    @classmethod
    def from_dict(cls, data: t.Dict[str, t.Any]) -> DictionaryEntry:
        et = data.get("et", None)
        try:
            if et and et[0][0] == "text":
                et = re.sub(r"[{]\S+[}]", "", et[0][1])
        except IndexError:
            print("IndexError")
            et = None

        return cls(
            id=data["meta"]["id"],
            word=data["meta"]["id"].split(":")[0],
            definitions=data["shortdef"],
            functional_label=data.get("fl", None),
            offensive=data["meta"]["offensive"],
            etymology=et,
            date=data.get("date", None),
        )


class DictionaryAPI:
    def __init__(self, api_key: str) -> None:
        self._api_key = api_key
        self._session: t.Optional[aiohttp.ClientSession] = None
        self._autocomplete_cache: t.Dict[str, t.List[str]] = {}
        self._entry_cache: t.Dict[str, t.List[DictionaryEntry]] = {}

    @property
    def session(self) -> aiohttp.ClientSession:
        if self._session is None:
            self._session = aiohttp.ClientSession()
        return self._session

    async def get_autocomplete(self, word: t.Optional[str] = None) -> t.List[str]:
        """Get autocomplete results for a word from the dictionary.

        Parameters
        ----------
        word : Optional[str]
            The word to get results for.

        Returns
        -------
        List[str]
            A list of strings representing the autocomplete results.

        Raises
        ------
        DictionaryException
            Failed to communicate with the Dictionary API.
        """

        if not word:
            return ["Start typing a word to get started..."]

        if word in self._autocomplete_cache:
            return self._autocomplete_cache[word]

        async with self.session.get(
            f"https://www.merriam-webster.com/lapi/v1/mwol-search/autocomplete?search={word}"
        ) as resp:
            if resp.status != 200:
                raise DictionaryException(
                    f"Failed to communicate with the dictionary API: {resp.status}: {resp.reason}"
                )

            results: t.List[str] = [
                doc.get("word") for doc in (await resp.json())["docs"] if doc.get("ref") == "owl-combined"
            ][:25]
            self._autocomplete_cache[word] = results

        return results

    async def get_entries(self, word: str) -> t.List[DictionaryEntry]:
        """Get entries for a word from the dictionary.

        Parameters
        ----------
        word : str
            The word to find entries for.

        Returns
        -------
        List[DictionaryEntry]
            A list of dictionary entries for the word.

        Raises
        ------
        DictionaryException
            Failed to communicate with the Dictionary API.
        """

        if word in self._entry_cache:
            return self._entry_cache[word]

        async with self.session.get(
            f"https://www.dictionaryapi.com/api/v3/references/collegiate/json/{word}?key={self._api_key}"
        ) as resp:
            if resp.status != 200:
                raise DictionaryException(
                    f"Failed to communicate with the dictionary API: {resp.status}: {resp.reason}"
                )
            payload = await resp.json()

            if isinstance(payload, dict):
                results: t.List[DictionaryEntry] = [DictionaryEntry.from_dict(data) for data in (payload)][:25]
                self._entry_cache[word] = results
                return results

            return []
