# Discord release announcements

The release command can add one announcement per version to
[the SkiEO Discord thread](https://discord.com/channels/1476002317626114111/1557305192871886898).
It uses an incoming webhook on the thread's parent channel. Announcements contain
the version's changelog entry and download links, and run after the SSH
publication and public HTTPS verification succeed.

No webhook is configured yet. The account requesting this integration does not
have server administration rights. Creating a webhook requires **Manage
Webhooks**, which can be delegated without granting Administrator. A member
with that permission must create it if the release maintainer lacks it.
[Discord documents this permission requirement](https://docs.discord.com/developers/resources/webhook#create-webhook).

## Ask a channel manager to create the webhook

Ask a member with Manage Webhooks to open **Server Settings → Integrations →
Webhooks**, create a webhook named **SkiEO releases**, and select the parent
text or forum channel containing this thread. They should share its URL
privately with the release maintainer. The release maintainer can then use the
URL without their own account having administration rights.
[Discord's setup guide](https://support.discord.com/hc/en-us/articles/228383668-Intro-to-Webhooks).

The destination IDs from the supplied link are:

| Field | Value |
| --- | --- |
| Server | `1476002317626114111` |
| Existing thread | `1557305192871886898` |
| Parent channel | Select the channel containing that thread in Discord |

The link does not expose the parent channel ID. Confirm the parent channel in
Discord before creating the webhook. The script checks the webhook's server
and requires Discord to confirm the target thread in its response.

Suggested request to the channel manager:

> Could you create an incoming webhook named “SkiEO releases” on the parent
> channel of https://discord.com/channels/1476002317626114111/1557305192871886898
> and share its URL privately? It will add a version announcement only after our
> downloads have been published and verified. I do not need administrator rights.

If a webhook cannot be provided, use the preview command below and post its
content manually. Automated sending remains disabled while the webhook is absent.

## Configure the release workstation

On the machine running `deployment/release_custom_map.py`, set
`SKIEOMOD_DISCORD_WEBHOOK_URL` to the incoming webhook URL. Keep it in the local
secret configuration or CI secrets, outside the repository. For a Bash session,
this reads it without displaying it or adding it to shell history:

```sh
read -r -s -p 'Discord webhook URL: ' SKIEOMOD_DISCORD_WEBHOOK_URL
export SKIEOMOD_DISCORD_WEBHOOK_URL
export SKIEOMOD_DISCORD_STATE_DIR="$HOME/.local/state/skieomod/discord"
```

Use a persistent state directory on the publication machine. By default,
receipts live in `build/discord-notifications/`; keep them between releases and
between publication retries. No webhook token is written to receipts or logs.

## Prepare and preview a release

Add a nonempty `## [1.20.10] - YYYY-MM-DD` entry to `CHANGELOG.md`, moving the
relevant Unreleased notes into it. Then prepare and test the release normally:

```sh
python3 deployment/release_custom_map.py 1.20.10 --prepare-only
```

The artifacts include `Changelog-1.20.10.md`, a frozen copy of the changelog,
and `discord-announcement-preview.json`. Preparation never contacts Discord.
To inspect an announcement without any network request or webhook:

```sh
python3 deployment/discord_releases.py 1.20.10 --dry-run \
  --changelog build/release-1.20.10/Changelog-1.20.10.md
```

You can preview the current notes immediately with
`python3 deployment/discord_releases.py 1.20.9 --dry-run`.

## Publish and announce

After testing the prepared game packages:

```sh
python3 deployment/release_custom_map.py 1.20.10 --publish-only
```

The command publishes the checked artifacts, including the versioned changelog
and the stable `downloads/changelog.md` link. It verifies the public loader
feed, then sends the announcement if the webhook environment variable is set.
`--skip-discord` suppresses the announcement for that invocation.

The webhook request uses `wait=true&thread_id=1557305192871886898` and
`allowed_mentions: {"parse": []}`. Discord confirms the message before its ID
is recorded. An archived thread is reopened by sending, while a locked thread
needs a channel manager to restore access.
[Webhook execution](https://docs.discord.com/developers/resources/webhook#execute-webhook),
[thread access](https://docs.discord.com/developers/topics/threads#locked-threads).

A webhook adds messages under its own name. It cannot edit the original post
written by a human account; webhook editing applies to messages sent with the
same webhook token. This workflow adds a chronological announcement for each
version. [Webhook message editing](https://docs.discord.com/developers/resources/webhook#edit-webhook-message).

## Recover a failed announcement

If Discord fails after HTTPS verification, the version is already public.
Retry the notifier instead of publishing the packages again:

```sh
python3 deployment/discord_releases.py 1.20.10 \
  --changelog build/release-1.20.10/Changelog-1.20.10.md
```

The standalone notifier checks that this is the current published version.
A confirmed receipt makes a repeat invocation return the same message ID
without sending again. Explicit Discord rejections can be retried after fixing
the webhook or thread access. Rate-limit retries honor Discord's `retry_after`
when the wait is at most 30 seconds; longer waits are reported for a later retry.
[Discord rate limits](https://docs.discord.com/developers/topics/rate-limits#exceeding-a-rate-limit).

If a timeout leaves delivery uncertain, the pending receipt prevents an
automatic second send. Check the thread. If the announcement exists, recover
its receipt without sending or editing a message:

```sh
python3 deployment/discord_releases.py 1.20.10 \
  --changelog build/release-1.20.10/Changelog-1.20.10.md \
  --confirm-message-id MESSAGE_ID
```

If no announcement exists, remove that version's pending receipt from the state
directory before retrying. If the machine or state directory changes, copy the
receipts so confirmed versions stay recorded.
