/**​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ Deciding what a failed sign-in is allowed to tell the person signing in.
 *
 * A backend that is down does not produce a network error when anything sits
 * in front of it. A reverse proxy answers 502, 503 or 504, and that is an
 * ordinary HTTP response: `fetch` resolves, `res.ok` is false, and the
 * `catch` branch that exists for "unable to connect" never runs. So the one
 * place a server outage actually lands is the same branch as a typo in a
 * password.
 *
 * That is not hypothetical. On 2026-08-29 our own demo application was down
 * for a full day while Caddy answered 502 for every request to it, and the
 * sign-in screen in front of it had exactly one sentence for the situation:
 * "Invalid email or password". Telling someone their password is wrong is the
 * single claim we can be sure is unfounded, because nothing ever read it.
 */

/** What kind of failure a sign-in response describes. */
export type LoginFailureKind = 'credentials' | 'unavailable';

/**
 * Classify a failed sign-in response by its status code.
 *
 * @param status - The HTTP status of the response that was not ok.
 * @returns `'unavailable'` when the server never got as far as checking the
 *   credentials, `'credentials'` when it did and refused them.
 *
 * 5xx covers both halves of the same story: our own server failing while
 * answering for itself, and a proxy in front of it reporting that it could
 * not reach the server at all. Neither of them looked at the password.
 * Everything else - 401, 403, 422 - is the server having read the request and
 * declined it, which is what the credentials wording is for.
 */
export function loginFailureKind(status: number): LoginFailureKind {
  return status >= 500 ? 'unavailable' : 'credentials';
}

/**
 * Classify a failed sign-in by its status and by what its body turned out to be.
 *
 * The status on its own cannot separate the two things a 4xx means, and the
 * split above left that half open. Our login endpoint answers a question about
 * credentials with a FastAPI error body every time: 401 for a refusal, 422 for
 * a malformed request, 429 for too many attempts, each one JSON carrying
 * `detail`. Something standing in front of us answers with its own page and no
 * `detail` at all - a WAF blocking the request with 403, a CDN rate-limiting it
 * with 429, a proxy that lost the route replying 404 out of its own HTML error
 * page. `res.json()` throws on those, which is why both sign-in screens already
 * end up with `null` there, and `null` then fell through to the credentials
 * wording.
 *
 * So a sub-500 response we could read no message out of never reached the part
 * of the system that can have an opinion about a password, and saying the
 * password is wrong about it is the same unfounded claim the 5xx split exists
 * to stop. A blocked or throttled request lands here too and is told the server
 * did not answer. That is not literally what happened to it, but it points at
 * the one action that helps, which is waiting, instead of at a password nothing
 * read.
 *
 * This cannot make a real refusal disappear. A wrong password, an unknown
 * account and a deactivated one are one and the same 401 with one and the same
 * `detail`, so all three still arrive here with a message and all three still
 * read as credentials, indistinguishable from each other.
 *
 * @param status - The HTTP status of the response that was not ok.
 * @param detail - The message extracted from the body, or `null` when the body
 *   held none: it was not JSON, or carried no error shape we recognise.
 * @returns `'credentials'` only when our own API answered about the credentials.
 */
export function loginFailureKindFromResponse(status: number, detail: string | null): LoginFailureKind {
  if (loginFailureKind(status) === 'unavailable') return 'unavailable';
  return detail ? 'credentials' : 'unavailable';
}
