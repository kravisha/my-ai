"""Files and images sent from the owner's phone.

Krish, 2026-09-16 17:36, from abroad: *"Please add FILE AND IMAGE ATTACHMENTS to
the Jarvis chat interface... When I press Send, transmit the attachment together
with my text to the receiving Claude/Jarvis session."*

Four properties are worth a suite here, and they fail in different directions.

**Nothing is quietly dropped.** The worst available outcome is not a refused
upload - it is a message that arrives looking complete with the file missing, so
that Krish believes a photo reached Claude and Claude was handed a sentence about
a photo he never got. The route and the socket refuse an attachment they cannot
resolve, and the page refuses to send while one is unresolved. That is asserted
from both ends.

**The path travels.** An attachment described to the engineer session without
where it is on disk is a message saying a file exists somewhere on the machine he
is already on. The path in the channel entry is the entire value of this feature
from the receiving end.

**The model is not handed a picture it cannot see.** The transcript is one string
per turn, so an image reaches the assistant as a name and a size. Asked what is
in the photo, a model given only a filename will describe a photo. The manifest
says the limit out loud, and there is a test that it does.

**The picker and the server agree.** The page's `accept` attributes and
`gateway/attachments.ALLOWED` are two statements of one list. Drift between them
is discovered by the owner, after a slow upload, in another country.

There is no JavaScript runtime in this suite, so the page's half is asserted
against its source - weaker than executing it, and not nothing: what it catches
is a page that posts to a route that has moved, or a send path that stopped
checking the tray.
"""

import base64
import json

import pytest

from app import model_gateway
from gateway import attachments, conversation, interface, roles, store, uiversion

PNG = b"\x89PNG\r\n\x1a\n" + b"not really pixels, and nothing here parses them"
JPEG = b"\xff\xd8\xff" + b"nor these"


@pytest.fixture(autouse=True)
def attachment_dir(tmp_path, monkeypatch):
    """Every test in this module writes into its own directory.

    Autouse and not optional: the default is the real shared folder beside
    Krish's message files, and a suite that wrote there would leave test files in
    the directory the Claude session reads.
    """
    target = tmp_path / "attachments"
    monkeypatch.setenv(attachments.DIRECTORY_ENV, str(target))
    return target


def page_source() -> str:
    return uiversion.VOICE_PAGE.read_text(encoding="utf-8")


def nothing_saved(directory) -> bool:
    """Asserted after every refusal. A rejected upload that left a file behind
    would fill the shared folder with things the owner was told did not arrive."""
    return not directory.exists() or not list(directory.iterdir())


def attach(client, token, name, data: bytes):
    return client.post(
        "/voice/attach",
        json={"name": name, "data_base64": base64.b64encode(data).decode("ascii")},
        headers={"Authorization": f"Bearer {token}"},
    )


def relay(client, token, text, ids=None):
    body = {"text": text}
    if ids is not None:
        body["attachments"] = ids
    return client.post("/voice/relay", json=body,
                       headers={"Authorization": f"Bearer {token}"})


class CapturingProvider:
    """One turn that answers, and keeps what it was asked.

    The assertion this exists for is what the *model* received: the attachment
    manifest has to be inside the message text, because that is the only thing a
    later turn will still have.
    """

    def __init__(self, reply="Noted."):
        self.reply = reply
        self.calls = []

    def complete(self, system, messages, tools, max_tokens=2048):
        raise AssertionError("the Gateway conversation must stream, not complete")

    def stream(self, system, messages, tools, max_tokens=2048):
        self.calls.append({"system": system, "messages": [dict(m) for m in messages]})
        yield {"type": "text", "text": self.reply}
        yield {"type": "final",
               "content": [{"type": "text", "text": self.reply}],
               "stop_reason": "end_turn"}


# --- what may be saved at all -------------------------------------------------------


def test_a_photo_is_saved_where_the_claude_session_can_read_it(attachment_dir):
    record = attachments.save("holiday.png", PNG)

    assert record["kind"] == attachments.IMAGE
    assert record["size"] == len(PNG)
    saved = attachment_dir / record["stored"]
    assert saved.read_bytes() == PNG
    assert record["path"] == str(saved)


def test_the_id_is_the_only_shape_that_is_ever_looked_up():
    """`load` globs `<id>-*` in one directory, so the id is the thing that must
    not be able to contain a separator. Asserted against the issuer rather than
    trusted: if `save` ever produces something ID_PATTERN rejects, the file is
    written and then unreachable."""
    record = attachments.save("notes.txt", b"hello")
    assert attachments.ID_PATTERN.match(record["id"])


def test_a_type_that_is_not_on_the_list_is_refused_and_nothing_is_written(attachment_dir):
    with pytest.raises(attachments.AttachmentError) as refused:
        attachments.save("installer.exe", b"MZ and then some")

    assert refused.value.status == 415
    assert nothing_saved(attachment_dir)


def test_a_file_with_no_extension_is_refused_with_something_he_can_act_on():
    with pytest.raises(attachments.AttachmentError) as refused:
        attachments.save("scan", b"bytes")

    assert refused.value.status == 415
    assert "extension" in refused.value.reason


def test_a_file_over_the_ceiling_is_refused_before_it_is_written(attachment_dir):
    with pytest.raises(attachments.AttachmentError) as refused:
        attachments.save("huge.pdf", b"%PDF-" + b"x" * attachments.MAX_BYTES)

    assert refused.value.status == 413
    # The refusal names the ceiling, because "too big" without a number sends him
    # back to the picker to guess.
    assert attachments.human_size(attachments.MAX_BYTES) in refused.value.reason
    assert nothing_saved(attachment_dir)


def test_the_ceiling_reads_as_the_number_the_page_promises():
    """The page's hint text says "15 MB each" in words a person reads. This is
    the same number, and it is a test because a decimal 15,000,000 prints as
    14.3 MB - a refusal that contradicts the label above the button."""
    assert attachments.human_size(attachments.MAX_BYTES) == "15.0 MB"


def test_an_empty_file_is_refused():
    with pytest.raises(attachments.AttachmentError):
        attachments.save("empty.txt", b"")


def test_a_file_at_exactly_the_ceiling_is_accepted():
    record = attachments.save("big.txt", b"x" * attachments.MAX_BYTES)
    assert record["size"] == attachments.MAX_BYTES


def test_a_name_that_is_a_path_cannot_leave_the_directory(attachment_dir):
    """The property, asserted the blunt way: whatever the name claims, the file
    is inside the one directory. `..` survives as characters in the stored name
    and has nowhere to go, because the name is only ever appended to an id."""
    record = attachments.save(r"..\..\Windows\System32\evil.txt", b"nothing doing")

    saved = attachment_dir / record["stored"]
    assert saved.is_file()
    assert saved.parent == attachment_dir
    assert "\\" not in record["stored"] and "/" not in record["stored"]


def test_a_very_long_name_is_shortened_and_keeps_its_extension():
    record = attachments.save("a" * 300 + ".pdf", b"%PDF-1.7")

    assert record["name"].endswith(".pdf")
    assert len(record["name"]) <= 80
    assert record["kind"] == attachments.DOCUMENT


def test_a_name_that_is_only_dots_still_gets_a_usable_one():
    with pytest.raises(attachments.AttachmentError):
        # No extension survives, so it is refused rather than stored as
        # something nobody can classify.
        attachments.save("....", b"bytes")


def test_a_file_whose_contents_do_not_match_its_name_is_refused():
    """A share sheet renaming a HEIC to .jpg is the real case. Storing it would
    put a file in front of the assistant described as something it is not."""
    with pytest.raises(attachments.AttachmentError) as refused:
        attachments.save("photo.png", JPEG)

    assert refused.value.status == 415


def test_a_format_with_no_magic_entry_is_stored_without_a_content_check():
    """Deliberate: the table covers the formats where a mismatch is meaningful.
    A .txt file has no header and must not need one."""
    record = attachments.save("notes.txt", b"just words")
    assert record["size"] == len(b"just words")


# --- finding one again --------------------------------------------------------------


def test_a_saved_attachment_can_be_loaded_back():
    saved = attachments.save("report.pdf", b"%PDF-1.7 and the rest")
    found = attachments.load(saved["id"])

    assert found is not None
    assert found["name"] == "report.pdf"
    assert found["path"] == saved["path"]
    assert found["kind"] == attachments.DOCUMENT


@pytest.mark.parametrize("hostile", [
    "", "   ", "not-an-id", "../../etc/passwd", "20260916-181530-a1b2c3d4-extra",
    "*", "20260916-181530-ZZZZZZZZ", None,
])
def test_a_string_that_is_not_an_id_returns_nothing_and_raises_nothing(hostile):
    """None rather than an exception, for every caller: a page that was reloaded
    since the upload sends a stale id, which is an ordinary event."""
    assert attachments.load(hostile) is None


def test_resolving_keeps_his_order_drops_repeats_and_names_what_is_gone():
    first = attachments.save("one.txt", b"first")
    second = attachments.save("two.txt", b"second")

    records, missing = attachments.resolve(
        [first["id"], second["id"], first["id"], "20260101-000000-deadbeef"])

    assert [record["name"] for record in records] == ["one.txt", "two.txt"]
    assert missing == ["20260101-000000-deadbeef"]


def test_what_the_page_is_told_leaves_out_where_the_file_is():
    """The page has no use for the path and it would put this machine's directory
    layout into anything that logs a response body."""
    record = attachments.save("holiday.png", PNG)
    published = attachments.public(record)

    assert "path" not in published
    assert "stored" not in published
    assert published["id"] == record["id"]
    assert published["size_human"]


# --- what the assistant is told ----------------------------------------------------


def test_a_text_file_is_quoted_to_the_assistant_in_full():
    record = attachments.save("todo.md", "# Ship attachments\n- the tray\n".encode("utf-8"))

    described = attachments.describe_for_model([record])

    assert "todo.md" in described
    assert "# Ship attachments" in described
    assert "- the tray" in described


def test_a_long_text_file_is_truncated_and_says_so():
    """The transcript is re-sent every turn, so an unbounded paste is a cost paid
    on every later question rather than once."""
    record = attachments.save("huge.log", b"x" * (attachments.INLINE_MAX_CHARS + 500))

    body = attachments.inline_text(record)

    assert body is not None
    assert "truncated" in body
    assert len(body) < attachments.INLINE_MAX_CHARS + 200


def test_an_image_is_not_quoted_and_the_assistant_is_told_he_cannot_see_it():
    """The regression that matters most in this module. Handed a filename and
    nothing else, a model asked what is in the photo will describe a photo."""
    record = attachments.save("receipt.png", PNG)

    assert attachments.inline_text(record) is None
    described = attachments.describe_for_model([record])
    assert "receipt.png" in described
    assert "cannot" in described
    assert "Claude can open" in described


def test_nothing_attached_adds_nothing_at_all():
    """The unattached message must be byte-for-byte what it was before this
    release. Every message he has ever sent is this case."""
    assert attachments.describe_for_model([]) == ""
    assert attachments.channel_block([]) == ""


def test_the_manifest_counts_what_is_actually_there():
    records = [attachments.save("one.txt", b"a"), attachments.save("two.png", PNG)]

    described = attachments.describe_for_model(records)

    assert "attached 2 files" in described
    assert "1. one.txt" in described
    assert "2. two.png" in described


def test_the_limits_the_prompt_states_are_the_limits_that_are_enforced():
    """Generated rather than typed: a prompt promising twenty megabytes while the
    route refuses at fifteen is the assistant telling him to try what cannot
    work."""
    paragraph = attachments.prompt_paragraph()

    assert attachments.human_size(attachments.MAX_BYTES) in paragraph
    assert str(attachments.MAX_PER_MESSAGE) in paragraph
    assert ".pdf" in paragraph and ".png" in paragraph


def test_the_operator_prompt_carries_the_attachment_paragraph():
    """Wired into the prompt behind his page, not only available. This is the
    half of "make him self aware about all the controls on his interface" that a
    new control has to repeat."""
    prompt = conversation.operator_prompt()

    assert "attach button" in prompt
    assert "15.0 MB" in prompt or attachments.human_size(attachments.MAX_BYTES) in prompt


def test_the_client_is_not_told_about_attachments():
    """A client meets a representative with no attach button, and cannot upload
    one: the capability is the operator's. Telling them about a control they do
    not have is the drift §95 was about."""
    client = conversation.client_prompt("Nadim", roles.ROLE_CLIENT)

    assert "attach button" not in client


def test_the_new_controls_are_declared_where_the_agent_reads_them():
    declared = {control.element_id for control in interface.CONTROLS}

    assert {"attach", "attachPhoto", "attachFile", "tray"} <= declared


# --- what the engineer session is told ---------------------------------------------


def test_the_channel_block_carries_the_path_he_has_to_open():
    record = attachments.save("screenshot.png", PNG)

    block = attachments.channel_block([record])

    assert record["path"] in block
    assert "screenshot.png" in block
    assert "image" in block


# --- the upload route ---------------------------------------------------------------


def test_uploading_needs_a_session(gateway_client, attachment_dir):
    response = gateway_client.post("/voice/attach",
                                   json={"name": "x.png", "data_base64": "AAAA"})

    assert response.status_code in (401, 403)
    assert not attachment_dir.exists() or not list(attachment_dir.glob("*"))


def test_uploading_returns_an_id_and_writes_the_file(gateway_client, gateway_token,
                                                     attachment_dir):
    response = attach(gateway_client, gateway_token, "holiday.png", PNG)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is True
    record = body["attachment"]
    assert attachments.ID_PATTERN.match(record["id"])
    assert record["kind"] == "image"
    assert "path" not in record
    assert len(list(attachment_dir.glob(record["id"] + "-*"))) == 1


def test_an_upload_that_did_not_survive_the_journey_is_refused(gateway_client, gateway_token):
    response = gateway_client.post(
        "/voice/attach",
        json={"name": "holiday.png", "data_base64": "this is not base64!!"},
        headers={"Authorization": f"Bearer {gateway_token}"},
    )

    assert response.status_code == 400
    assert "again" in response.json()["detail"]


def test_the_route_refuses_the_types_the_module_refuses(gateway_client, gateway_token,
                                                        attachment_dir):
    response = attach(gateway_client, gateway_token, "installer.exe", b"MZ")

    assert response.status_code == 415
    assert nothing_saved(attachment_dir)


def test_the_route_returns_the_ceiling_refusal_as_a_413(gateway_client, gateway_token,
                                                        monkeypatch):
    """The ceiling itself is asserted against the module above. What this checks
    is that the route carries the refusal's own status out rather than turning
    every attachment problem into a 400 - the page shows the detail and the
    status is what tells it apart from a broken upload.

    The limit is lowered rather than a real 15 MB body being built: base64 of
    fifteen megabytes through the test client costs seconds and proves nothing
    the module's own test has not."""
    monkeypatch.setattr(attachments, "MAX_BYTES", 32)

    response = attach(gateway_client, gateway_token, "big.txt", b"x" * 64)

    assert response.status_code == 413
    assert "limit" in response.json()["detail"]


def test_a_client_session_cannot_put_a_file_on_this_machine(gateway_client, gateway_conn,
                                                            attachment_dir):
    """`publish`, not `converse`, and this is the narrowing. Writing a file onto
    the machine the owner's Gateway runs on is not something a client role does,
    and `converse` would have handed it to every client who signs in."""
    token, _ = store.create_session(gateway_conn, 3600, roles.ROLE_CLIENT, "a-client")

    response = attach(gateway_client, token, "holiday.png", PNG)

    assert response.status_code == 403
    assert not attachment_dir.exists() or not list(attachment_dir.glob("*"))


# --- the relay: a file reaching Claude ---------------------------------------------


def test_a_relayed_attachment_puts_its_path_in_the_entry(gateway_client, gateway_token,
                                                         tmp_path, monkeypatch):
    """The end Krish asked for: press Send, and the receiving session is given
    the file. What makes it work is the path."""
    channel = tmp_path / "channel.md"
    channel.write_text("# Channel\n", encoding="utf-8")
    monkeypatch.setenv("JARVIS_CLAUDE_CHANNEL", str(channel))
    uploaded = attach(gateway_client, gateway_token, "screenshot.png", PNG).json()["attachment"]

    response = relay(gateway_client, gateway_token, "Look at this page.", [uploaded["id"]])

    assert response.status_code == 200, response.text
    body = channel.read_text(encoding="utf-8")
    assert body.startswith("# Channel\n"), "the relay truncated history"
    assert "Look at this page." in body
    assert "ATTACHMENTS (1)" in body
    assert "screenshot.png" in body
    saved = attachments.load(uploaded["id"])
    assert saved["path"] in body
    assert response.json()["attachments"][0]["id"] == uploaded["id"]


def test_the_attachment_block_stays_inside_the_entry(gateway_client, gateway_token,
                                                     tmp_path, monkeypatch):
    """`gateway/main.voice_inbox` and the wake script both split these files on
    "\\n## ". A block written between entries would belong to neither, and the
    phone would read out a message with no attachment and an attachment with no
    message."""
    channel = tmp_path / "channel.md"
    monkeypatch.setenv("JARVIS_CLAUDE_CHANNEL", str(channel))
    uploaded = attach(gateway_client, gateway_token, "notes.txt", b"words").json()["attachment"]

    relay(gateway_client, gateway_token, "Notes attached.", [uploaded["id"]])
    relay(gateway_client, gateway_token, "And a second message.", [])

    entries = channel.read_text(encoding="utf-8").split("\n## ")[1:]
    assert len(entries) == 2
    assert "ATTACHMENTS" in entries[0]
    assert "ATTACHMENTS" not in entries[1]


def test_a_relay_naming_an_attachment_that_is_gone_is_refused(gateway_client, gateway_token,
                                                              tmp_path, monkeypatch):
    """Refused rather than sent without it. A message that reads as delivered
    with the file missing is the failure this whole suite is arranged around."""
    channel = tmp_path / "channel.md"
    monkeypatch.setenv("JARVIS_CLAUDE_CHANNEL", str(channel))

    response = relay(gateway_client, gateway_token, "Here it is.",
                     ["20260101-000000-deadbeef"])

    assert response.status_code == 404
    assert not channel.exists(), "the message went without the file it named"


def test_a_relay_with_too_many_attachments_is_refused(gateway_client, gateway_token,
                                                      tmp_path, monkeypatch):
    channel = tmp_path / "channel.md"
    monkeypatch.setenv("JARVIS_CLAUDE_CHANNEL", str(channel))
    ids = [attach(gateway_client, gateway_token, f"n{index}.txt",
                  f"file {index}".encode()).json()["attachment"]["id"]
           for index in range(attachments.MAX_PER_MESSAGE + 1)]

    response = relay(gateway_client, gateway_token, "All of them.", ids)

    assert response.status_code == 400
    assert not channel.exists()


def test_a_message_with_nothing_attached_is_written_exactly_as_before(
        gateway_client, gateway_token, tmp_path, monkeypatch):
    """Every message he has ever sent is this case, and the release must not
    change one character of it."""
    channel = tmp_path / "channel.md"
    monkeypatch.setenv("JARVIS_CLAUDE_CHANNEL", str(channel))

    relay(gateway_client, gateway_token, "Just words.")

    body = channel.read_text(encoding="utf-8")
    assert body.endswith("Just words.\n")
    assert "ATTACHMENT" not in body


# --- the socket: a file reaching Jarvis -------------------------------------------


def send_over_socket(client, token, payload):
    frames = []
    socket = client.websocket_connect("/ws")
    socket.__enter__()
    try:
        socket.send_json({"type": "auth", "token": token})
        socket.receive_json()          # ready
        socket.send_json(payload)
        while True:
            frame = socket.receive_json()
            frames.append(frame)
            if frame["type"] in ("done", "error"):
                break
    finally:
        socket.__exit__(None, None, None)
    return frames


def test_the_assistant_is_handed_the_attachment_with_the_message(gateway_client,
                                                                 gateway_token):
    """End to end on the box-1 side: he types a sentence, attaches a note, and
    the model receives both in one message."""
    uploaded = attach(gateway_client, gateway_token, "todo.md",
                      b"- fix the label\n").json()["attachment"]
    provider = CapturingProvider()
    model_gateway.set_provider(provider)
    try:
        frames = send_over_socket(gateway_client, gateway_token, {
            "type": "message",
            "text": "What is in this list?",
            "attachments": [uploaded["id"]],
        })
    finally:
        model_gateway.set_provider(None)

    assert [frame for frame in frames if frame["type"] == "error"] == []
    sent = provider.calls[0]["messages"][-1]["content"]
    assert "What is in this list?" in sent
    assert "todo.md" in sent
    assert "- fix the label" in sent, "a text attachment must reach the model quoted"


def test_the_manifest_is_inside_the_message_so_later_turns_still_have_it(gateway_client,
                                                                        gateway_token):
    """The transcript is one string per turn. A manifest carried beside the text
    would be invisible to every later turn, and "what was in that file" is the
    obvious second question."""
    uploaded = attach(gateway_client, gateway_token, "notes.txt", b"the notes").json()["attachment"]
    provider = CapturingProvider()
    model_gateway.set_provider(provider)
    try:
        send_over_socket(gateway_client, gateway_token,
                         {"type": "message", "text": "Read this.",
                          "attachments": [uploaded["id"]]})
        send_over_socket(gateway_client, gateway_token,
                         {"type": "message", "text": "What did it say?"})
    finally:
        model_gateway.set_provider(None)

    second_turn = provider.calls[1]["messages"]
    assert any("notes.txt" in message["content"] for message in second_turn)


def test_a_message_naming_an_attachment_that_is_gone_is_refused(gateway_client,
                                                                gateway_token):
    provider = CapturingProvider()
    model_gateway.set_provider(provider)
    try:
        frames = send_over_socket(gateway_client, gateway_token, {
            "type": "message", "text": "Look at this.",
            "attachments": ["20260101-000000-deadbeef"],
        })
    finally:
        model_gateway.set_provider(None)

    assert frames[-1]["type"] == "error"
    assert not provider.calls, "the turn ran without the file it was asked about"


def test_too_many_attachments_on_one_message_is_refused(gateway_client, gateway_token):
    ids = [attach(gateway_client, gateway_token, f"n{index}.txt",
                  f"file {index}".encode()).json()["attachment"]["id"]
           for index in range(attachments.MAX_PER_MESSAGE + 1)]
    provider = CapturingProvider()
    model_gateway.set_provider(provider)
    try:
        frames = send_over_socket(gateway_client, gateway_token,
                                  {"type": "message", "text": "All of them.",
                                   "attachments": ids})
    finally:
        model_gateway.set_provider(None)

    assert frames[-1]["type"] == "error"
    assert not provider.calls


def test_a_message_with_no_attachments_reaches_the_model_unchanged(gateway_client,
                                                                   gateway_token):
    provider = CapturingProvider()
    model_gateway.set_provider(provider)
    try:
        send_over_socket(gateway_client, gateway_token,
                         {"type": "message", "text": "Just a question."})
    finally:
        model_gateway.set_provider(None)

    assert provider.calls[0]["messages"][-1]["content"] == "Just a question."


def test_a_client_session_cannot_attach_to_a_conversation(gateway_client, gateway_conn):
    """Checked at the socket as well as at the upload. A capability filtered at
    one door and not the other is the authorization shape this Gateway has had
    wrong before (§92)."""
    token, _ = store.create_session(gateway_conn, 3600, roles.ROLE_CLIENT, "a-client")
    provider = CapturingProvider()
    model_gateway.set_provider(provider)
    try:
        frames = send_over_socket(gateway_client, token, {
            "type": "message", "text": "Here is a file.",
            "attachments": ["20260916-120000-aaaaaaaa"],
        })
    finally:
        model_gateway.set_provider(None)

    assert frames[-1]["type"] == "error"
    assert "not permitted" in frames[-1]["error"]
    assert not provider.calls


# --- the page's half ---------------------------------------------------------------


def accept_tokens() -> set[str]:
    """Every extension the page's two pickers offer.

    Parsed into tokens rather than searched as substrings, because `.doc` is
    inside `.docx` and a substring check would pass on a page that had lost
    one of them."""
    page = page_source()
    tokens = set()
    for line in page.splitlines():
        if "accept=" not in line:
            continue
        value = line.split("accept=", 1)[1].strip().strip(">").strip('"')
        for token in value.split(","):
            token = token.strip()
            if token.startswith("."):
                tokens.add(token.lower())
    return tokens


def test_the_picker_offers_exactly_what_the_server_accepts():
    """The drift that would be discovered by the owner, after a slow upload, in
    another country: a picker offering a type the route refuses."""
    offered = accept_tokens()
    allowed = set(attachments.ALLOWED)

    assert offered == allowed, (
        f"only in the page: {sorted(offered - allowed)}; "
        f"only in gateway/attachments.ALLOWED: {sorted(allowed - offered)}")


def test_the_photo_picker_asks_for_the_photo_library():
    """`accept="image/*"` is what makes a phone offer the camera and the photo
    library rather than a file browser. Krish asked for those as separate
    choices."""
    page = page_source()
    assert 'id="photoInput"' in page
    assert "image/*" in page
    assert 'id="fileInput"' in page


def test_the_page_uploads_to_the_route_that_exists():
    page = page_source()
    assert "/voice/attach" in page
    assert "data_base64" in page


def test_the_page_names_the_gap_between_a_pull_and_a_restart():
    """voice.html is read from disk on every request while the modules behind it
    are held in memory, so the attach button can exist minutes before the upload
    route does - which is how a raw placeholder reached his phone on 2026-09-15.
    A chip reading "Not Found" is a mystery; a chip saying the Gateway has not
    been restarted yet is a wait."""
    page = page_source()

    assert "r.status === 404" in page
    assert "has not been restarted with attachments yet" in page


def test_the_page_sends_the_ids_with_both_kinds_of_message():
    """Box 1 to Jarvis on the socket, box 2 to Claude over the relay. Krish's
    requirement 7 is that the attachment goes with the text, whichever of the two
    he presses."""
    page = page_source()
    assert 'type: "message", text, attachments: ids' in page
    assert "JSON.stringify({ text, attachments: ids })" in page


def test_the_page_refuses_to_send_while_a_file_is_unresolved():
    """The page's half of "nothing is quietly dropped". Both send paths ask, and
    a page that stopped asking would send his words without his photo."""
    page = page_source()
    assert page.count("attachmentsNotReady()") >= 3, (
        "both send paths must check the tray before sending")


def test_the_page_limits_are_the_servers_limits():
    """Two numbers on two sides of one upload. A page that allowed more than the
    route would refuse at fifteen megabytes after a long upload on a hotel
    connection."""
    page = page_source()
    assert f"const MAX_ATTACH = {attachments.MAX_PER_MESSAGE};" in page
    assert f"const MAX_ATTACH_BYTES = {attachments.MAX_BYTES};" in page


def test_the_tray_never_renders_a_filename_as_markup():
    """A filename comes from a picker and lands on a page holding a session
    token."""
    page = page_source()
    tray = page.split("function paintTray", 1)[1].split("\n  }\n", 1)[0]
    assert "textContent" in tray
    # The one innerHTML in there empties the tray before it is rebuilt. Anything
    # that *wrote* markup would be the mistake.
    assert 'innerHTML = ""' in tray
    assert "innerHTML +=" not in tray
    assert "innerHTML = `" not in tray


def test_attaching_is_not_sending():
    """The same property box 2 has. Picking a file uploads it and stops; nothing
    in the attachment code path presses either send button."""
    page = page_source()
    body = page.split("async function addFiles", 1)[1].split("\n  function attachmentIds", 1)[0]
    assert "sendRelay" not in body
    assert "/voice/relay" not in body
    assert "ws.send" not in body
