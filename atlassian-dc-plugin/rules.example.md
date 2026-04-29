# Rules for "<alias>"

> Place this file at `~/.config/atlassian/rules/<alias>.md` (Linux/macOS) or
> `%APPDATA%\atlassian\rules\<alias>.md` (Windows). One file per instance.
> Override the location via `$ATLASSIAN_CONFIG_DIR`.

## Global

- Kein Issue ohne Assignee anlegen — bei fehlendem Assignee zurückfragen.
- Default-Priority ist "Medium". Setze sie nur, wenn der User sie ausdrücklich nennt.
- Bei JQL-Suchen niemals ohne `project = ...`-Filter laufen; sonst Confirm anfragen.

## Project HALLO

- Stories brauchen Epic-Link (Custom Field). Frage vor dem Erstellen nach dem Epic-Key.
- Bug-Tickets brauchen "Steps to Reproduce" in der Beschreibung.
- Erlaubte Issue-Types: Story, Bug, Task. Keine Sub-tasks ohne Parent.

## Project FOO

- Alle Issues automatisch in den aktuellen Sprint hängen.
- Reporter-Feld nicht auf den ausführenden Bot setzen, sondern beim User belassen.
