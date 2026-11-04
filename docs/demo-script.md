# Prompt Vault demo script

A short walkthrough for a screen recording (target 2–3 minutes, no narration
required — the UI does the talking). Capture with a screen recorder at 1440p
and trim to the essential beats. Drop the resulting GIF/video next to this
file and link it from the README.

## Beats

1. **Search (10 s).** Open the library, type in the search box. Show ranked
   results with the match highlighted, the category sidebar and the filters
   chips. Clear the search.
2. **Detail (20 s).** Open a prompt with variables. Show the title, body,
   category, tags, source and license. Fill a variable inline, copy the
   rendered result to the clipboard (the copy confirmation appears), then copy
   the raw body.
3. **Import wizard (40 s).** Go to the Data page, Import tab. Pick "CSV with a
   header row", drop in a file, walk through the mapping step (the columns are
   auto-mapped), review the preview (new / duplicate / invalid chips), and
   commit. Show the "Import: N new, 0 replaced, N skipped" result and the new
   prompts in the library.
4. **Trash (15 s).** Trash a prompt, show it in the Trash page, restore it.
5. **Backup (10 s).** In a terminal, run `promptvault backup` and show the
   timestamped snapshot landing in the backups directory.

## Tips

- Reset the library to the seed data before recording (`promptvault reset --yes`
  or reload the seed), so the search results look realistic.
- Use a small import file (2–3 rows) so the wizard steps stay visible.
- Keep the window narrow enough that the mobile drawer is not triggered, but
  wide enough that the sidebar and detail pane are both visible (a maximized
  window on a 1440p display works well).
