"""Prompt texts, and the seam a prompt server can later be plugged into.

The texts sat next to the client that sends them, which was fine while they
were two constants. They are about to stop being: the wording of the
extraction prompt is the open half of W-1, and comparing one wording with
another means changing it without a deploy. Langfuse keeps prompts in
versions and labels for exactly that, and ties every generation it traces to
the version that produced it -- which is what turns "this prompt is better"
into a number rather than an impression.

So this module is the boundary that makes such a move a change of one class.
A caller asks for a prompt by name and hands over the variables; where the
text came from is not its business. The static store keeps the texts in the
repository, which is what CI and any machine without keys run on, and it
stays the fallback once a remote store exists: a prompt server that cannot
be reached has to degrade to the wording in the commit, never to no wording.

Placeholders are written in Langfuse's ``{{variable}}`` syntax rather than
str.format's, so a text can be copied into the prompt server untouched.
"""

import re
from collections.abc import Mapping
from typing import Protocol

from langfuse import Langfuse
from langfuse.model import TextPromptClient

JOB_POST_SKILLS = "job-post-skills"
"""The prompt that reads what a posting demands."""

RESUME_SKILLS = "resume-skills"
"""The prompt that reads what a resume evidences."""

MATCH_SUGGESTIONS = "match-suggestions"
"""The prompt that turns a gap into resume bullet points (FR-3)."""

PRODUCTION = "production"
"""The label a running application reads. A new version is written first and
labelled afterwards, so editing a prompt is not the same act as shipping it."""

CACHE_TTL_SECONDS = 300
"""How long a fetched prompt is served from memory. Long, because a prompt
changes a few times a day at most, and every miss is a blocking request on the
path of an LLM call. An expired entry is refreshed in a background thread and
the stale text is served meanwhile, so this is the only fetch anybody waits
for."""

FETCH_TIMEOUT_SECONDS = 3
FETCH_RETRIES = 1
"""Both deliberately short: a prompt server that is slow must not become the
latency of the application. What is waited for here is an improvement on a
text that is already in the process (NFR-2)."""

PLACEHOLDER = re.compile(r"\{\{\s*(\w+)\s*\}\}")
"""What a variable looks like. Whitespace inside the braces is allowed
because the Langfuse editor puts it there."""

JOB_POST_SKILLS_TEMPLATE = """\
Read the job posting below and list the concrete skills, tools, licences and \
qualifications a candidate has to evidence for it.

The posting can be for any trade -- a kitchen, a warehouse, a workshop, a \
care home, an office, a software team. Answer in the words of that trade.

Rules:
- One skill per entry, lower case.
- Name the thing itself, not the sentence around it: "experience with \
containerisation" gives "docker" only if the posting names Docker, otherwise \
"containerisation"; "able to operate a forklift" gives "forklift".
- A licence, certificate or legal requirement the posting asks for is a \
requirement like any other and must appear in the list: "forklift licence", \
"category b licence", "haccp", "first aid". A certificate the employer offers \
to pay for is not.
- Where a word has two spellings, use the British one, so that a posting and \
a resume come back written the same way: "licence", "tyre", "organise".
- At most three words per entry.
- Include what the posting states as a requirement or a strong preference. \
Leave out benefits, company description, the contract type and anything the \
employer offers rather than asks for.
- Leave out traits no resume could evidence: "team player", "good \
communication", "attention to detail". A named duty is not a trait: \
"customer service", "cash handling" and "night shifts" stay.
- No duplicates, and no entry that is a restatement of another.

Job posting:
{{content}}
"""
"""One side of the comparison, and the reason the spelling rule exists twice:
what a posting demands and what a resume evidences are read by two separate
calls, so a normalisation that only one of them performs is worse than none.
British spelling is picked for being one choice, not for being right."""

RESUME_SKILLS_TEMPLATE = """\
Read the resume below and list the skills, tools, licences and qualifications \
it gives evidence of.

The resume can come from any trade -- a kitchen, a warehouse, a workshop, a \
care home, an office, a software team. Answer in the words of that trade.

Rules:
- One skill per entry, lower case.
- Only what the resume actually evidences. Do not infer a skill from a \
neighbouring one: a resume naming Docker does not thereby know Kubernetes, \
and a cook who ran the cold starters section is not thereby a pastry chef.
- Use the ordinary full name, so that the same skill written in two ways \
comes back once: "k8s" as "kubernetes", "postgres" as "postgresql", "js" as \
"javascript", "ms excel" as "excel", "cat c+e" as "category c+e licence".
- Where a word has two spellings, use the British one: "licence", "tyre", \
"organise".
- Keep licences, certificates and tickets the resume claims: "forklift \
licence", "first aid", "haccp", "food hygiene certificate". Leave out the \
school or body that issued them.
- At most three words per entry.
- Leave out job titles, employer names and dates. Leave out traits: "team \
player", "hard working".
- No duplicates, and no entry that is a restatement of another.

Resume:
{{content}}
"""
"""The other half of the comparison. The instruction to expand an abbreviation
is what this whole call is for: the resume says k8s and the posting says
kubernetes, the resume says cat c+e and the posting says category c+e licence,
and no rule about plurals will ever bring those together.

Its rules mirror the posting prompt's on purpose. Two lists normalised by two
different instructions meet in cover() as two different vocabularies, and the
score is then measuring the prompts against each other."""

MATCH_SUGGESTIONS_TEMPLATE = """\
You are helping a candidate adapt their resume to one job posting.
Write resume bullet points that close the gaps listed below.
Ground every bullet point in the posting and in the candidate's own \
experience; do not invent employers, dates, technologies or achievements that \
appear in neither.

Write them the way a strong resume is written:
- Open with what the candidate did, not with a duty they were responsible for.
- Name the tool, skill or licence the posting names, in the posting's own \
words: write "Kubernetes" where the posting says Kubernetes and "HACCP" where \
it says HACCP, not a paraphrase of either.
- Keep the number the resume already gives you -- covers served, deliveries a \
day, vehicles serviced, invoices booked, latency, team size -- and never \
invent one it does not.
- One line per entry, past tense, no adjectives about the candidate.
- Write in the vocabulary of the trade the posting is from. A kitchen, a \
warehouse and a software team describe good work in different words.

A gap the resume gives you nothing to work with is not a bullet point: put it \
in notes, one sentence, addressed to the candidate. bullet_points is copied \
into a resume as it stands, so anything written about the resume rather than \
for it belongs in notes.

# Job posting
{{title}}
{{posting}}

# Candidate resume
{{resume}}

# Missing keywords
{{keywords}}
"""
"""The sections are part of the prompt rather than of the code: what the model
is shown, in what order, under which heading, is the thing being tuned. The
code only decides what goes into each, and says "none" where there is nothing.

How to write a bullet point used to arrive as retrieved chunks of career
articles. The knowledge base holds nothing but postings now, so the advice
lives here instead -- which is the better address for it anyway: it is the
same advice on every match, and here it is versioned and its effect is
measurable, rather than being whatever five chunks a nearest-neighbour search
happened to return.

The instruction about notes has to stay whatever else changes. A schema field
the prompt never mentions comes back empty, and the meta-comment it exists to
catch goes back to riding along in bullet_points (W-2)."""

TEMPLATES: Mapping[str, str] = {
    JOB_POST_SKILLS: JOB_POST_SKILLS_TEMPLATE,
    RESUME_SKILLS: RESUME_SKILLS_TEMPLATE,
    MATCH_SUGGESTIONS: MATCH_SUGGESTIONS_TEMPLATE,
}
"""Every prompt the application ships with, by name. The names are the ones a
prompt server would store them under, so moving a text out of here changes
where it is read from and nothing else."""


def render_template(template: str, variables: Mapping[str, str]) -> str:
    """Fill every ``{{placeholder}}`` in the template, and nothing else.

    Both halves of a mismatch are errors rather than silences. A placeholder
    nobody supplied would reach the model as the literal text
    ``{{content}}`` -- a prompt with the document missing -- and the answer
    to that still parses, because an empty skill list is also what a posting
    with no requirements looks like. A variable no placeholder uses is the
    same mistake seen from the other side, usually a rename that landed in
    one place only.
    """
    seen: set[str] = set()

    def substitute(match: re.Match[str]) -> str:
        name = match.group(1)

        if name not in variables:
            raise ValueError(f"prompt variable {name!r} was not supplied")

        seen.add(name)

        return variables[name]

    filled = PLACEHOLDER.sub(substitute, template)
    unused = sorted(set(variables) - seen)

    if unused:
        raise ValueError(f"prompt has no placeholder for {', '.join(unused)}")

    return filled


class PromptStore(Protocol):
    """Where the service layer gets the text it sends to a model.

    One method, because a caller has exactly one question. Everything a
    remote store adds -- versions, labels, caching, falling back -- lives
    behind it, so the day it arrives no service changes.

    The prompt name is positional-only: it shares a signature with the
    variables, and a prompt with a variable called name would otherwise be
    unrenderable.
    """

    def render(self, name: str, /, **variables: str) -> str:
        """Return the named prompt with its variables filled in."""
        ...

    def warm(self) -> None:
        """Fetch whatever the first render would otherwise wait for."""
        ...


class StaticPromptStore:
    """The texts in this module, rendered without leaving the process.

    The default for tests and for a machine with no Langfuse keys, and the
    reason the suite is deterministic and offline: a prompt is a dictionary
    lookup, not a request.
    """

    def __init__(self, templates: Mapping[str, str] | None = None) -> None:
        """Serve the shipped texts, or the ones handed over instead."""
        self._templates = TEMPLATES if templates is None else templates

    def render(self, name: str, /, **variables: str) -> str:
        """Return the named prompt, failing loudly when there is none.

        An unknown name is a typo in the caller, and a prompt that silently
        came back empty would be sent to the model as an empty instruction.
        """
        if name not in self._templates:
            raise KeyError(f"no prompt named {name!r}")

        return render_template(self._templates[name], variables)

    def warm(self) -> None:
        """Nothing to fetch: the texts are already in the process."""


class LangfusePromptStore:
    """Prompts as the server serves them, with this repository as the floor.

    Two things are bought here. A wording can be changed and labelled without
    a deploy, which is what makes W-1 measurable rather than arguable. And
    every generation is tied to the version that produced it, so cost and
    quality can be read per version instead of per commit.

    Nothing is bet on the server being up. Each fetch carries the shipped text
    as its fallback, so an unreachable Langfuse costs the wording of the
    commit and not the request; the SDK also keeps serving an expired cache
    entry while it refreshes it in the background. A prompt that is not in
    TEMPLATES has no floor to fall back to and is refused outright -- better
    than sending a model an empty instruction.

    Rendering deliberately does not use the SDK's own compile(): it leaves an
    unfilled placeholder in the text as literal {{...}}, which is exactly the
    silent failure render_template exists to prevent.
    """

    def __init__(
        self, client: Langfuse, templates: Mapping[str, str] | None = None
    ) -> None:
        """Read prompts through this client, falling back to these texts."""
        self._client = client
        self._templates = TEMPLATES if templates is None else templates

    def render(self, name: str, /, **variables: str) -> str:
        """Return the named prompt, and record which version was used.

        The version is hung on the observation that is open, which is the
        generation about to be made when the caller is a provider client. A
        caller that renders outside one hangs it on whatever span it is in --
        still true, less useful. A fallback is never recorded: the SDK skips
        it, because a version number that names nothing on the server would
        make the trace lie about what it read.
        """
        prompt = self._fetch(name)
        self._client.update_current_generation(prompt=prompt)

        return render_template(prompt.prompt, variables)

    def warm(self) -> None:
        """Fetch every shipped prompt, so no request pays for the first one.

        Called at startup, where a blocking fetch costs nobody anything. It
        cannot fail: an unreachable server leaves the fallback in the cache,
        which is what the process would have used anyway.
        """
        for name in self._templates:
            self._fetch(name)

    def _fetch(self, name: str) -> TextPromptClient:
        if name not in self._templates:
            raise KeyError(f"no prompt named {name!r}")

        return self._client.get_prompt(
            name,
            label=PRODUCTION,
            fallback=self._templates[name],
            cache_ttl_seconds=CACHE_TTL_SECONDS,
            max_retries=FETCH_RETRIES,
            fetch_timeout_seconds=FETCH_TIMEOUT_SECONDS,
        )


def create_prompt_store(tracer: Langfuse | None) -> PromptStore:
    """Read prompts from Langfuse when there is one, from the repository else.

    It takes the client the lifespan already built rather than reaching for
    get_client(), and that is the whole point: a client built without keys
    disables itself, and get_prompt on a disabled client raises instead of
    returning the fallback. None here is the same condition seen one step
    earlier, where it can still be answered with a store that never fetches.
    """
    return StaticPromptStore() if tracer is None else LangfusePromptStore(tracer)
