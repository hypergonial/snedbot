# Privacy Policy:

_By using Sned, you agree to Discord's [Terms of Service](https://discord.com/terms)_

---


## 1. What Information do we collect:

Sned retains a little information about users as possible.

What we do collect, and store persistently are:

- Your Discord [Snowflake](https://discord.dev/reference#snowflakes)
- The ID of guilds where Sned is used
- Certain user-submitted content
- Certain user-submitted preferences (e.g. timezone)
- A list of moderation actions performed on users (journal)

## 2. Why do we store this information?

Sned provides multiple services that action upon users (either first or second party individuals). 

Because of the asyncrhonous nature of these services, and the requirement of a context to act within, it's a requisite to know what guild, and who the actions are targeted toward.

This data is only stored as long as it's required, and is immediately removed from temporary and persistent data stores when it's no longer in use. Any information that is stored persistently is done out of neccessicity.

In the context of user-submitted data, we store this information because it is generally required to, as this information can be retroactively retrieved, if permitted.

Examples of user-submitted content that is stored persistently include:

- Reminders
- Tags
- Moderation Journal
- Starboard entries
- Rolebuttons

In most instances, this information is easily user-accessible, and is removed from both temporary and persistent data stores immediately when not in use.

Any information that is overridden also follows this rule, and the previous content is inaccessible from that point on. 

Discord Snowflakes are also used for diagnostic purposes, and help link issues with specific users or guilds.

## 3. How do we collect this information?

Your discord ID is provided by Discord's [API](https://discord.dev).

Under normal circumstances, this information is not stored persistently, nor for any extended period of time in temporary storage.

We may collect this information temporarily or indefinitely under certain circumstances, under the restriction that you have been involved with Sned and it's services, directly or indirectly. 

Moderators of any server that has authorized Sned to operate on their guild may pass your user ID as an argument to a service provided by Sned, which may require storing it persistently.

Alternatively some services provided by Sned accessible to non-moderators may store information about you (such as your ID). This information is as restrictive as possible, bearing only enough context to provide core functionality to the aforementioned services.


## 4. What is this information used for?

Information stored by Sned is only used for the purposes stated by the related service it is used for. This information is never shared with third parties, and only leaves the confines of the service when it is required by a first-party entity.

Some of Sned's services use persistently stored data to be sent back to the user at a later time.

Furthermore, storing Discord identifiers (IDs, Snowflakes) allows for robust error analysis that would otherwise be inacessible or otherwise infeasible. 

By storing this information, it enables us to not only improve upon the product being offered to the end user posthaste, but contact users and/or server owners if necessary. 

It also allows users to contact us in regards to issues that may occur with Sned, so that they may be linked with a corresponding log or metric recorded by Sned for these diagnostic purposes.

The use of IDs links end users to certain metadata held about them, both from Discord and tracked internally by Sned's services. Sned may, if configured, act atonomously on this metadata should configured circumstances be met. Metadata attached to users is deleted in a cascading manner, and is removed should the user's primary entity be removed from our data stores for any reason.

## 5. How to be informed when this policy updates:

Should this policy be updated in the future, for any reason, an announcement will be made on Sned's [Discord Server](https://discord.gg/KNKr8FPmJa).

## 6. Contacting:

Any questions or concerns can be answered via Discord, and joining Sned's [Discord Server](https://discord.gg/KNKr8FPmJa)

## 7. How is user information protected?
Both temporary and persistent data stores are located on a remote server.

Sensitive data can only be accessed via a single account, which requires an SSH key to log into, which is also stored in a secured location.
