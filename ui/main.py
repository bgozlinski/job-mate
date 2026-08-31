"""Streamlit dev client for JobMate: accounts, resumes and the knowledge base.

A development tool, not part of the product. It speaks to the API over HTTP
exactly as any other client would; the HTTP side of that lives in `client`.

Run it with the API already up:

    uv run --group ui streamlit run ui/main.py

The API address comes from JOBMATE_API_URL, which deliberately does not live
in `.env`: the api container mounts that file and its Settings forbid extra
keys, so an entry meant for this client would stop the server from starting.
"""

import json
from datetime import datetime
from typing import Any

import httpx
import streamlit as st

from client import API_URL, TOKEN_KEY, authorized, send, succeeded

RESUME_GENERATION_KEY = "resume_uploader_generation"
DOCUMENT_GENERATION_KEY = "document_uploader_generation"

UPLOAD_TYPES = ["pdf", "docx", "txt", "md"]

SOURCE_TYPES = ["job_post", "article", "qa"]

MAX_RESUME_LENGTH = 100_000
MAX_DOCUMENT_LENGTH = 200_000

PAGE_SIZE = 20
MAX_PAGE_SIZE = 100

SHOWN_KEY = "documents_shown"
FILTER_KEY = "documents_source_type"
MATCH_KEY = "match_result"

MATCH_BUDGET = 20


def text_field(name: str, value: str) -> dict[str, str]:
    """Turn a text box into the field to send, or into nothing at all.

    An empty box means the caller did not fill it in, which is a missing
    field. Sending it as "" would store an empty string in a column meant to
    be null, and for source_url would fail validation outright.
    """
    return {name: value.strip()} if value.strip() else {}


def parse_metadata(text: str) -> dict[str, Any] | None:
    """Read the metadata box as a JSON object, or say why it cannot be.

    Checked here rather than left to the API because the upload route reports
    any unreadable form field with a single message that does not name the
    field. An empty box is an empty object; None means the text was wrong and
    nothing should be sent.
    """
    if not text.strip():
        return {}

    try:
        value: Any = json.loads(text)
    except json.JSONDecodeError as exc:
        st.error(f"Metadata is not valid JSON: {exc}")
        return None

    if not isinstance(value, dict):
        st.error("Metadata has to be a JSON object.")
        return None

    return value


def chunks_label(count: int) -> str:
    """Say how many chunks a source split into, in English rather than data."""
    return f"{count} chunk" if count == 1 else f"{count} chunks"


def file_part(uploaded: Any) -> dict[str, tuple[str, bytes, str]]:
    """Build the multipart file field.

    No Content-Type of our own anywhere near this: httpx builds the multipart
    body and the boundary that goes with it, and a header set by hand loses
    the boundary.
    """
    return {"file": (uploaded.name, uploaded.getvalue(), uploaded.type or "text/plain")}


def log_in(email: str, password: str) -> str | None:
    """Exchange credentials for an access token, or show why it failed.

    The endpoint takes JSON, not an OAuth2 form, and answers the same 401 for
    an unknown address as for a wrong password -- so the message is passed on
    as it comes rather than guessed at.
    """
    response = send("POST", "/auth/login", json={"email": email, "password": password})
    if response is None or not succeeded(response, httpx.codes.OK):
        return None

    return str(response.json()["access_token"])


def render_login() -> None:
    """Show the login form and keep the token it earns."""
    with st.form("login"):
        email = st.text_input("Email")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Log in")

    if not submitted:
        return

    token = log_in(email, password)
    if token is not None:
        # Session state only: in this process's memory, for this browser tab.
        # Never a query parameter -- that would put the token in the URL.
        st.session_state[TOKEN_KEY] = token
        st.rerun()


def fetch_resumes() -> list[Any] | None:
    """Fetch the caller's resumes, newest first, or None if the call failed."""
    response = authorized("GET", "/resumes")
    if response is None or not succeeded(response, httpx.codes.OK):
        return None

    return list(response.json())


def render_resume_upload() -> None:
    """Upload a resume file, then empty the widget that carried it."""
    generation = int(st.session_state.get(RESUME_GENERATION_KEY, 0))

    with st.form("resume-upload"):
        uploaded = st.file_uploader(
            "Resume file (max 5 MB)",
            type=UPLOAD_TYPES,
            key=f"resume-file-{generation}",
        )
        role = st.text_input("Target role (optional)", key=f"resume-role-{generation}")
        submitted = st.form_submit_button("Upload")

    if not submitted:
        return

    if uploaded is None:
        st.warning("Pick a file first.")
        return

    with st.spinner("Reading the resume..."):
        response = authorized(
            "POST",
            "/resumes/upload",
            files=file_part(uploaded),
            data=text_field("target_role", role),
        )

    if succeeded(response, httpx.codes.CREATED):
        st.session_state[RESUME_GENERATION_KEY] = generation + 1
        st.rerun()


def render_resume_paste() -> None:
    """Store a resume typed or pasted straight into the page."""
    with st.form("resume-paste", clear_on_submit=True):
        content = st.text_area("Resume text", height=200)
        role = st.text_input("Target role (optional)")
        submitted = st.form_submit_button("Save")

    if not submitted:
        return

    if not content.strip():
        st.warning("The text is empty.")
        return

    if len(content) > MAX_RESUME_LENGTH:
        st.error(f"The text is longer than {MAX_RESUME_LENGTH} characters.")
        return

    payload = {"content": content} | text_field("target_role", role)
    with st.spinner("Reading the resume..."):
        response = authorized("POST", "/resumes", json=payload)

    if succeeded(response, httpx.codes.CREATED):
        st.rerun()


def render_resume(resume: Any) -> None:
    """Show one stored resume: where it came from, its text, and a way out."""
    # astimezone with no argument moves the stored UTC instant into the
    # reader's own zone; without it every row reads two hours early here.
    created = datetime.fromisoformat(resume["created_at"]).astimezone()
    source = resume["original_filename"] or "pasted text"
    role = resume["target_role"] or "no target role"

    with st.container(border=True):
        st.markdown(f"**{source}** - {role}")
        st.caption(
            f"{created:%Y-%m-%d %H:%M} | {len(resume['content'])} characters"
            f" | {resume['id']}"
        )

        # Behind a click on purpose: the column holds up to 100 000
        # characters, and drawing every one of them for every row makes the
        # page crawl by the third resume.
        with st.expander("Show text"):
            st.text(resume["content"])

        if st.button("Delete", key=f"delete-{resume['id']}"):
            response = authorized("DELETE", f"/resumes/{resume['id']}")
            # 204: there is no body to read, only a status that says it
            # worked.
            if succeeded(response, httpx.codes.NO_CONTENT):
                st.rerun()


def render_resumes() -> None:
    """Draw the resumes tab: what is stored, and the two ways to add more."""
    st.subheader("Add a resume")
    render_resume_upload()

    with st.expander("...or paste the text"):
        render_resume_paste()

    st.subheader("Stored resumes")
    # Fetched on every rerun rather than cached: the list changes with every
    # write on this page, and a cache would also outlive the account it was
    # filled for.
    resumes = fetch_resumes()
    if resumes is None:
        return

    if not resumes:
        st.info("No resumes yet.")
        return

    for resume in resumes:
        render_resume(resume)


def report_ingest(response: httpx.Response | None) -> bool:
    """Tell a newly ingested source from one that was already there.

    201 and 200 are both success, and the difference is the whole point of
    deduplication (FR-1): the second says this text is in the knowledge base
    already and names the document it landed in the first time. Reporting it
    as an error would turn a feature into a failure.
    """
    if response is None or not succeeded(response, httpx.codes.CREATED, httpx.codes.OK):
        return False

    document: Any = response.json()
    chunks = document["chunk_count"]

    if response.status_code == httpx.codes.CREATED:
        st.success(f"Ingested as {document['id']} ({chunks_label(chunks)}).")
    else:
        st.info(
            f"Already in the knowledge base as {document['id']}"
            f" ({chunks_label(chunks)})."
        )

    return True


def reset_documents_page() -> None:
    """Start the listing from the first page again after the filter changes."""
    st.session_state[SHOWN_KEY] = PAGE_SIZE


def render_document_upload() -> None:
    """Ingest a source from a file, then empty the widget that carried it."""
    generation = int(st.session_state.get(DOCUMENT_GENERATION_KEY, 0))

    with st.form("document-upload"):
        uploaded = st.file_uploader(
            "Source file (max 5 MB)",
            type=UPLOAD_TYPES,
            key=f"document-file-{generation}",
        )
        source_type = st.selectbox(
            "Source type", SOURCE_TYPES, key=f"document-type-{generation}"
        )
        title = st.text_input("Title (optional)", key=f"document-title-{generation}")
        url = st.text_input("Source URL (optional)", key=f"document-url-{generation}")
        metadata = st.text_area(
            "Metadata, a JSON object (optional)",
            placeholder='{"role": "backend", "seniority": "mid"}',
            key=f"document-metadata-{generation}",
        )
        submitted = st.form_submit_button("Ingest file")

    if not submitted:
        return

    if uploaded is None:
        st.warning("Pick a file first.")
        return

    parsed = parse_metadata(metadata)
    if parsed is None:
        return

    data = (
        {"source_type": str(source_type)}
        | text_field("title", title)
        | text_field("source_url", url)
    )
    # Multipart has no notion of a nested value, so metadata travels as JSON
    # text and the route parses it back.
    if parsed:
        data["metadata"] = json.dumps(parsed)

    with st.spinner("Embedding the source..."):
        response = authorized(
            "POST", "/documents/upload", files=file_part(uploaded), data=data
        )

    if report_ingest(response):
        # No rerun here: the listing below is drawn after this call, so it
        # already includes the new source, and rerunning would wipe the
        # message saying whether it was new or a duplicate.
        st.session_state[DOCUMENT_GENERATION_KEY] = generation + 1


def render_document_paste() -> None:
    """Ingest a source typed or pasted straight into the page."""
    with st.form("document-paste", clear_on_submit=True):
        content = st.text_area("Source text", height=200, key="document-paste-content")
        source_type = st.selectbox(
            "Source type", SOURCE_TYPES, key="document-paste-type"
        )
        title = st.text_input("Title (optional)", key="document-paste-title")
        url = st.text_input("Source URL (optional)", key="document-paste-url")
        metadata = st.text_area(
            "Metadata, a JSON object (optional)",
            placeholder='{"role": "backend", "seniority": "mid"}',
            key="document-paste-metadata",
        )
        submitted = st.form_submit_button("Ingest text")

    if not submitted:
        return

    if not content.strip():
        st.warning("The text is empty.")
        return

    if len(content) > MAX_DOCUMENT_LENGTH:
        st.error(f"The text is longer than {MAX_DOCUMENT_LENGTH} characters.")
        return

    parsed = parse_metadata(metadata)
    if parsed is None:
        return

    payload: dict[str, Any] = (
        {"source_type": str(source_type), "content": content, "metadata": parsed}
        | text_field("title", title)
        | text_field("source_url", url)
    )

    with st.spinner("Embedding the source..."):
        response = authorized("POST", "/documents", json=payload)

    report_ingest(response)


def render_document(document: Any) -> None:
    """Show one source in the knowledge base."""
    created = datetime.fromisoformat(document["created_at"]).astimezone()
    title = document["title"] or "untitled"

    with st.container(border=True):
        st.markdown(f"**{title}** - {document['source_type']}")
        st.caption(
            f"{created:%Y-%m-%d %H:%M} | {chunks_label(document['chunk_count'])}"
            f" | {document['id']}"
        )

        if document["source_url"]:
            st.markdown(f"[{document['source_url']}]({document['source_url']})")

        # A source with no chunks is in the database and invisible to
        # retrieval, which is worth saying out loud rather than leaving as a
        # zero in a caption.
        if not document["chunk_count"]:
            st.warning("No chunks: nothing about this source can be retrieved.")

        if document["metadata"]:
            with st.expander("Metadata"):
                st.json(document["metadata"])


def render_document_list() -> None:
    """List the knowledge base, a page at a time, optionally filtered."""
    source_type = st.selectbox(
        "Source type",
        ["all", *SOURCE_TYPES],
        key=FILTER_KEY,
        on_change=reset_documents_page,
    )
    shown = int(st.session_state.get(SHOWN_KEY, PAGE_SIZE))

    # Asking for every row shown so far, from the top, rather than paging by
    # offset: the listing is rewritten by every ingestion above it, and a
    # stale offset over a shifted list is what shows a row twice.
    params: dict[str, Any] = {"limit": shown, "offset": 0}
    if source_type != "all":
        params["source_type"] = source_type

    response = authorized("GET", "/documents", params=params)
    if response is None or not succeeded(response, httpx.codes.OK):
        return

    documents = list(response.json())
    if not documents:
        st.info("Nothing in the knowledge base yet.")
        return

    for document in documents:
        render_document(document)

    # A short page is the end of the listing: the route returns no total, so
    # this is how a caller learns there is nothing more.
    if len(documents) < shown:
        return

    if shown >= MAX_PAGE_SIZE:
        st.caption(
            f"The listing returns at most {MAX_PAGE_SIZE} rows."
            " Narrow the filter to see the rest."
        )
        return

    if st.button("Load more"):
        st.session_state[SHOWN_KEY] = min(shown + PAGE_SIZE, MAX_PAGE_SIZE)
        st.rerun()


def render_documents() -> None:
    """Draw the documents tab: the knowledge base and the ways to add to it."""
    st.subheader("Add a source")
    render_document_upload()

    with st.expander("...or paste the text"):
        render_document_paste()

    st.subheader("Knowledge base")
    st.caption(
        "Shared by every account: sources added by anyone are listed here,"
        " and there is no delete route yet."
    )
    render_document_list()


def fetch_job_posts() -> list[Any] | None:
    """Fetch the postings a resume can be matched against.

    Filtered in the request rather than in the page: matching against an
    article is a 422, and a posting that cannot be picked is better than an
    error explaining why it should not have been.
    """
    response = authorized(
        "GET", "/documents", params={"source_type": "job_post", "limit": MAX_PAGE_SIZE}
    )
    if response is None or not succeeded(response, httpx.codes.OK):
        return None

    return list(response.json())


def resume_label(resume: Any) -> str:
    """Name a resume in a way the reader recognises and no other row shares.

    The id fragment is not decoration: two uploads of files with the same
    name in the same minute would otherwise collapse into one entry of the
    picker, and one of them would become unreachable.
    """
    created = datetime.fromisoformat(resume["created_at"]).astimezone()
    source = resume["original_filename"] or "pasted text"

    return f"{source} - {created:%Y-%m-%d %H:%M} ({resume['id'][:8]})"


def document_label(document: Any) -> str:
    """Name a job post the same way, and for the same reason."""
    created = datetime.fromisoformat(document["created_at"]).astimezone()
    title = document["title"] or "untitled"

    return f"{title} - {created:%Y-%m-%d %H:%M} ({document['id'][:8]})"


def run_match(resume_id: str, document_id: str) -> None:
    """Score one resume against one posting and keep the answer.

    The result goes into session state rather than straight onto the page:
    the next click anywhere reruns the script, and a result held only in a
    local variable would be gone -- at the price of the most expensive route
    in the application (NFR-2).
    """
    with st.spinner("Retrieving and scoring..."):
        response = authorized(
            "POST", f"/resumes/{resume_id}/match", json={"document_id": document_id}
        )

    if response is None or not succeeded(response, httpx.codes.OK):
        return

    st.session_state[MATCH_KEY] = {
        "resume_id": resume_id,
        "document_id": document_id,
        "result": response.json(),
    }


def render_words(title: str, words: list[str], empty: str) -> None:
    """Show one side of the keyword comparison."""
    st.markdown(f"**{title}**")
    st.write(", ".join(words) if words else empty)


def render_lines(title: str, subtitle: str, lines: list[str], empty: str) -> None:
    """Show one of the two lists of prose the model produced."""
    st.markdown(f"**{title}** — {subtitle}")

    if not lines:
        st.caption(empty)
        return

    for line in lines:
        st.markdown(f"- {line}")


def render_match_result(result: Any) -> None:
    """Show one match, worst news first."""
    score = float(result["score"])
    st.metric("Score", f"{score:.1%}")
    st.progress(score)

    # Missing before matched: it is the half of the comparison the reader can
    # act on.
    render_words("Missing from the resume", result["missing_keywords"], "Nothing.")
    render_words("Matched", result["matched_keywords"], "Nothing.")

    # Two lists, not one: suggestions are text for the resume, notes are
    # remarks about it, and a reader who cannot tell them apart would paste a
    # remark into their CV.
    render_lines(
        "Suggestions", "text for the resume", result["suggestions"], "None offered."
    )
    render_lines("Notes", "remarks about the resume", result["notes"], "None.")

    chunk_ids = result["retrieved_chunk_ids"]
    with st.expander(f"What the answer was built from ({len(chunk_ids)})"):
        st.caption(
            "Identifiers only. Nothing in the API returns a chunk's text, so"
            " reading what the model saw means Langfuse or SQL."
        )
        st.code("\n".join(chunk_ids), language=None)


def render_stored_match(resume_id: str, document_id: str) -> None:
    """Show the last match, and only for the pair it was actually run on.

    Storing the pair beside the result is what stops a score from being
    redrawn under a posting it was never about, once the picker moves on.
    """
    stored: Any = st.session_state.get(MATCH_KEY)
    if stored is None:
        return

    if stored["resume_id"] != resume_id or stored["document_id"] != document_id:
        return

    render_match_result(stored["result"])


def render_match() -> None:
    """Draw the match tab: pick a resume, pick a posting, spend the budget."""
    resumes = fetch_resumes()
    documents = fetch_job_posts()
    if resumes is None or documents is None:
        return

    if not resumes:
        st.info("No resumes yet. Add one in the Resumes tab first.")
        return

    if not documents:
        st.info("No job posts yet. Add one in the Documents tab first.")
        return

    by_resume = {resume_label(resume): resume for resume in resumes}
    by_document = {document_label(document): document for document in documents}

    chosen_resume = st.selectbox("Resume", list(by_resume), key="match-resume")
    chosen_document = st.selectbox("Job post", list(by_document), key="match-document")

    resume_id = str(by_resume[str(chosen_resume)]["id"])
    document_id = str(by_document[str(chosen_document)]["id"])

    st.caption(
        "One match embeds a query and calls an LLM; the budget is"
        f" {MATCH_BUDGET} an hour, separate from ingestion."
    )

    if st.button("Match"):
        run_match(resume_id, document_id)

    render_stored_match(resume_id, document_id)


def render_account(user: Any) -> None:
    """Show the account behind the stored token, with a way out."""
    st.success(f"Logged in as {user['email']}")
    st.json(user)

    if st.button("Log out"):
        st.session_state.pop(TOKEN_KEY, None)
        st.rerun()


def main() -> None:
    """Draw the page for whichever half of the session we are in.

    The account call doubles as the session check: it is the one request made
    on every rerun, so an expired token is noticed here, once, rather than by
    whichever tab happens to be open.
    """
    st.set_page_config(page_title="JobMate (dev)", page_icon=":compass:")
    st.title("JobMate — dev client")
    st.caption(f"API: {API_URL}")

    account = authorized("GET", "/auth/me")
    if account is None or not succeeded(account, httpx.codes.OK):
        render_login()
        return

    resumes_tab, documents_tab, match_tab, account_tab = st.tabs(
        ["Resumes", "Documents", "Match", "Account"]
    )
    with resumes_tab:
        render_resumes()
    with documents_tab:
        render_documents()
    with match_tab:
        render_match()
    with account_tab:
        render_account(account.json())


main()
