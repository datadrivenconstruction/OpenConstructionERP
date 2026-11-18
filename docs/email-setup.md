# Email and SMTP setup

OpenConstructionERP sends mail for password resets, tender invitations, document
delivery and notifications. This page is the whole of the setup: what to set, how to
pick the port, and how to tell whether it is working.

If you have already filled in the `SMTP_*` settings and nothing arrives, read the next
section first. It is the most common cause by a wide margin.

## The setting people miss

Filling in the `SMTP_*` settings is not enough on its own. The platform also has to be
told to use them, and it is not told by default.

```env
EMAIL_BACKEND=smtp
```

Without that line the platform runs its `console` transport, which writes each message
into the application log and treats it as delivered. Nothing errors, nothing is
rejected, and the log line looks like a send. Mail simply never leaves the machine. If
you configured a host, a user and a password and saw no complaint from anywhere, this
was almost certainly why.

Current builds warn about this at the first attempted send:

```
WARNING app.core.email.service: [email] SMTP settings are present but EMAIL_BACKEND is
'console', so no mail is sent - the 'console' transport only records messages. Set
EMAIL_BACKEND=smtp to deliver them.
```

On an older build you will not see that warning, and the silence is not a sign that the
settings are correct.

## Every setting, by its real name

Put these in `backend/.env`, or set them as environment variables on the service.

| Setting | Default | What it is |
|---|---|---|
| `EMAIL_BACKEND` | `console` | Transport to use. Set to `smtp` to actually send. |
| `SMTP_HOST` | empty | Your provider's outgoing mail server, sometimes called the submission or relay server. |
| `SMTP_PORT` | `587` | Port on that server. See the rule below. |
| `SMTP_TLS` | `true` | Upgrade the connection with STARTTLS after connecting. |
| `SMTP_USER` | empty | Login name. Usually the full mailbox address. |
| `SMTP_PASSWORD` | empty | Password for that login. Note the full word `PASSWORD`. |
| `SMTP_FROM` | `info@datadrivenconstruction.io` | Address messages are sent from. Change this to your own. |
| `NOTIFICATION_EMAIL_DAILY_CAP_PER_RECIPIENT` | `20` | Most automatic notification mails (reminders, escalations, digests) one address gets per UTC day. Over it the mail is logged and dropped; the in-app notification stays. `0` turns the cap off. |
| `NOTIFICATION_EMAIL_DAILY_CAP_PER_INSTANCE` | `300` | The same ceiling for the whole server. Verification, password-reset and other mail a person asks for is never counted against either cap. |

Two things about the names themselves, because both cost people an evening:

`SMTP_PASSWORD` is the whole word. `SMTP_PASS` is a different variable used by a
separate component and it does not configure the platform. If you set `SMTP_PASS`, the
platform connects with a username and no password, and a submission server refuses that.

Every setting also works with an `OE_` prefix, so `OE_SMTP_HOST` and `SMTP_HOST` are the
same setting. The unprefixed name wins if you somehow set both. Nothing else is
accepted: a name that is close but not exact is ignored in silence and the default
applies, which looks exactly like the setting having no effect.

`EMAIL_BACKEND` takes four values. `smtp` sends. `console` writes messages to the log
and is the default. `noop` discards them. `memory` keeps them in a list for tests. Only
`smtp` puts mail on the network.

## The port and encryption rule

This is the single most common mistake after the one above, and it is worth stating as a
rule rather than as an example.

**Use port 587 with `SMTP_TLS=true`.** The connection opens in the clear and is upgraded
to encryption with STARTTLS before the password is sent. Nearly every provider offers
this, and it is the combination the platform is built around.

The other combinations, and what each one does:

| Port | `SMTP_TLS` | Result |
|---|---|---|
| 587 | `true` | Correct. Use this. |
| 587 | `false` | The password would cross the network unprotected. Most providers reject the login. |
| 465 | either | Not supported. See below. |
| 25 | `false` | Server-to-server relaying, not authenticated submission. Use it only for a mail relay on your own network that accepts unauthenticated mail from the application. |

Port 465 expects the connection to be encrypted from the very first byte, which is a
different scheme from STARTTLS and one this platform does not currently speak. If your
provider offers both, choose 587. If it offers only 465, the platform cannot send
through it directly today; put a local relay in front that accepts submission on 587 and
forwards onward, or ask us at info@datadrivenconstruction.io.

The platform now refuses port 465 immediately with a message saying so. Before that
change, port 465 produced a fifteen-second pause followed by a message about the
connection closing unexpectedly, which named neither the port nor the encryption.

## A worked example

A typical hosted mailbox provider gives you an outgoing server name, tells you to use
port 587 with STARTTLS, and expects the full email address as the username. That is the
shape most providers have, and it is this:

```env
EMAIL_BACKEND=smtp
SMTP_HOST=smtp.your-provider.example
SMTP_PORT=587
SMTP_TLS=true
SMTP_USER=noreply@yourcompany.example
SMTP_PASSWORD=the-password-for-that-mailbox
SMTP_FROM=OpenConstructionERP <noreply@yourcompany.example>
```

Restart the backend after changing these. The settings are read once at startup.

Providers vary in ways that matter more than their names, so match yours by shape:

- **The username is not always what you expect.** Many providers want the full address,
  some want the part before the `@`, and a few issue a separate login that looks nothing
  like the mailbox. Using the wrong form produces an authentication failure, not a hint.
- **Accounts with two-factor authentication usually need an application-specific
  password.** Your normal account password will be rejected even though it is correct,
  because interactive logins and mail logins are treated differently. Generate a
  dedicated password in the provider's security settings and use that.
- **You may only send from addresses the account owns.** Setting `SMTP_FROM` to an
  address the mailbox is not authorised for gets the message refused at the point of
  sending, even though the login succeeded.
- **Large providers may require the sending domain to carry SPF, DKIM and DMARC records
  before they will accept or deliver your mail.** This is DNS work on the domain, not
  configuration in the platform.

## How to tell whether it is working

Start with the settings themselves. On the Integrations screen, the Email card's Test
button reports whether the server is configured to send and names any contradiction it
finds. It reads the live server configuration and does not open a connection, so it
tells you whether the platform will try to send, not whether your provider will accept
the message. It is the fastest way to rule out the silent cases above.

To confirm real delivery end to end, trigger a genuine send and watch the log. The
password reset on the sign-in screen is the easiest one to reach. Ask for a reset for an
account you can read the mailbox of, then look at the backend log.

A successful send logs this:

```
INFO app.core.email.smtp: [email:smtp] sent to=someone@example.com subject='Reset your password'
```

Note that the reset screen itself always says the same thing whether or not the message
was sent. That is deliberate: a different answer for a known and an unknown address
would let anyone test which addresses have accounts. The log is the place to look, not
the screen.

If the send failed, the log names the reason. These are the ones you are likely to meet:

| What the log says | What it means |
|---|---|
| `EMAIL_BACKEND is 'console', so no mail is sent` | The transport is not `smtp`. See the top of this page. |
| `SMTP_HOST is empty` | `EMAIL_BACKEND=smtp` is set but there is no server to send to. |
| `auth failed` | Username or password rejected. Check the username form and whether the account needs an application-specific password. |
| `network error: ConnectionRefusedError` | Nothing is listening on that host and port. Usually a wrong port or a wrong host name. |
| `server disconnected or timed out` | The connection opened and then went quiet. Usually outbound mail is blocked by a firewall, or the server expected encryption from the first byte. |
| `does not support STARTTLS on this port` | `SMTP_TLS=true` on a port that does not offer the upgrade. Check the port against your provider's documentation. |
| `recipient refused` | The server accepted your login but rejected the destination address. |
| `SMTP_PORT=465 requires implicit TLS` | Use 587. See the port rule above. |
| `Sender address not owned` or a `550` on sending | `SMTP_FROM` is an address this account is not allowed to send as. |

## Running without email

Email is optional. With `EMAIL_BACKEND` left at `console` the platform runs normally:
every feature works, and messages that would have been sent are written to the log
instead. Nothing else depends on outbound mail being configured, so an air-gapped or
mail-free install is a supported way to run.

The one thing to know is that password resets cannot reach the user by mail in that
mode. An administrator can set a password directly instead.

## Still stuck

Collect the backend log around the moment of a send attempt and the settings you used
with the password removed, and write to info@datadrivenconstruction.io.
