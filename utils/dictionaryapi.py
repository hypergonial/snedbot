from __future__ import annotations

import datetime
import re
import typing as t

import aiohttp
import attr
import yarl

# The idea for creating this module, along with the URL for the M-W autocomplete endpoint was found here:
# https://github.com/advaith1/dictionary

URBAN_SEARCH_URL = "https://www.urbandictionary.com/define.php?term={term}"
URBAN_JUMP_URL = URBAN_SEARCH_URL + "&defid={defid}"
URBAN_API_SEARCH_URL = "https://api.urbandictionary.com/v0/define?term={term}"

MW_AUTOCOMPLETE_URL = "https://www.merriam-webster.com/lapi/v1/mwol-search/autocomplete?search={word}"
MW_SEARCH_URL = "https://www.dictionaryapi.com/api/v3/references/collegiate/json/{word}?key={key}"


class UrbanException(Exception):
    """Base exception for Urban Dictionary API errors."""


class DictionaryException(Exception):
    """An exception raised if the connection to the Dictionary API fails."""


@attr.frozen(weakref_slot=False)
class UrbanEntry:
    """A dictionary entry in the Urban Dictionary."""

    word: str
    """The word this entry represents."""

    definition: str
    """The definition of the word."""

    defid: int
    """The ID of the definition."""

    example: str
    """An example of the word."""

    thumbs_up: int
    """The amount of thumbs up the word has."""

    thumbs_down: int
    """The amount of thumbs down the word has."""

    author: str
    """The author of the word."""

    written_on: datetime.datetime
    """The date the entry was created."""

    @property
    def jump_url(self) -> str:
        """The URL to jump to the entry."""
        return str(yarl.URL(URBAN_JUMP_URL.format(term=self.word, defid=self.defid)))

    @staticmethod
    def parse_urban_string(string: str) -> str:
        """Parse a string from the Urban Dictionary API, replacing references with markdown hyperlinks."""
        return re.sub(
            r"\[([^[\]]+)\]",
            lambda m: f"{m.group(0)}({yarl.URL(URBAN_SEARCH_URL.format(term=m.group(0)[1:-1]))})",
            string,
        )

    @classmethod
    def from_dict(cls, data: t.Dict[str, t.Any]) -> UrbanEntry:
        return cls(
            word=data["word"],
            definition=cls.parse_urban_string(data["definition"]),
            defid=data["defid"],
            example=cls.parse_urban_string(data["example"]),
            thumbs_up=data["thumbs_up"],
            thumbs_down=data["thumbs_down"],
            author=data["author"],
            written_on=datetime.datetime.fromisoformat(data["written_on"].replace("Z", "+00:00")),
        )


@attr.frozen(weakref_slot=False)
class DictionaryEntry:
    """A dictionary entry in the Merriam-Webster Dictionary."""

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
            et = None

        return cls(
            id=data["meta"]["id"],
            word=data["meta"]["id"].split(":")[0],
            definitions=data["shortdef"],
            functional_label=data.get("fl", None),
            offensive=data["meta"].get("offensive") or False,
            etymology=et,
            date=data.get("date", None),
        )


class DictionaryClient:
    def __init__(self, api_key: str) -> None:
        self._api_key = api_key
        self._session: t.Optional[aiohttp.ClientSession] = None
        self._autocomplete_cache: t.Dict[str, t.List[str]] = {}
        self._mw_entry_cache: t.Dict[str, t.List[DictionaryEntry]] = {}
        self._urban_entry_cache: t.Dict[str, t.List[UrbanEntry]] = {}

    @property
    def session(self) -> aiohttp.ClientSession:
        if self._session is None:
            self._session = aiohttp.ClientSession()
        return self._session

    async def get_urban_entries(self, word: str) -> t.List[UrbanEntry]:
        """Get entries for a word from the Urban dictionary.

        Parameters
        ----------
        word : str
            The word to find entries for.

        Returns
        -------
        List[UrbanEntry]
            A list of dictionary entries for the word.

        Raises
        ------
        UrbanException
            Failed to communicate with the Urban API.
        """
        if words := self._urban_entry_cache.get(word, None):
            return words

        async with self.session.get(URBAN_API_SEARCH_URL.format(term=word)) as resp:
            if resp.status != 200:
                raise UrbanException(f"Failed to get urban entries for {word}: {resp.status}: {resp.reason}")
            data = await resp.json()

            if data["list"]:
                self._urban_entry_cache[word] = [UrbanEntry.from_dict(entry) for entry in data["list"]]
                return self._urban_entry_cache[word]

            return []

    async def get_mw_autocomplete(self, word: t.Optional[str] = None) -> t.List[str]:
        """Get autocomplete results for a word from the Merriam-Webster dictionary.

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

        if words := self._autocomplete_cache.get(word, None):
            return words

        async with self.session.get(MW_AUTOCOMPLETE_URL.format(word=word)) as resp:
            if resp.status != 200:
                raise DictionaryException(
                    f"Failed to communicate with the dictionary API: {resp.status}: {resp.reason}"
                )

            results: t.List[str] = [
                doc.get("word") for doc in (await resp.json())["docs"] if doc.get("ref") == "owl-combined"
            ][:25]
            self._autocomplete_cache[word] = results

        return results

    async def get_mw_entries(self, word: str) -> t.List[DictionaryEntry]:
        """Get entries for a word from the Merriam-Webster dictionary.

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

        if words := self._mw_entry_cache.get(word, None):
            return words

        async with self.session.get(MW_SEARCH_URL.format(word=word, key=self._api_key)) as resp:
            if resp.status != 200:
                raise DictionaryException(
                    f"Failed to communicate with the dictionary API: {resp.status}: {resp.reason}"
                )
            payload = await resp.json()

            if payload and isinstance(payload[0], dict):
                results: t.List[DictionaryEntry] = [DictionaryEntry.from_dict(data) for data in (payload)][:25]
                self._mw_entry_cache[word] = results
                return results

            return []


# Copyright (C) 2022-present HyperGH

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program.  If not, see: https://www.gnu.org/licenses
