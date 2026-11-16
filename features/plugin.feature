Feature: A plugin that installs cleanly and keeps its promises
  As someone about to install this plugin
  I want its structure and its security promises to be checked on every change
  So that what the README says is what I get

  Background:
    Given the plugin repository

  Scenario: Every skill is well formed
    Then every skill has a SKILL.md whose name is its folder name
    And every skill description says when to use it and fits in 1024 characters
    And no skill refers to the old workspace layout

  Scenario: Skills only refer to scripts that exist
    Then every script a skill refers to exists

  Scenario: The manifests are valid
    Then the manifests are valid and agree on the plugin name

  Scenario: The rules that init writes cover every skill
    Then the rules written by init name every skill

  Scenario: The rules send every paper that is read through the read skill
    Then the rules written by init route paper reading through the read skill
    And the arxiv skill routes reading a paper through the read skill
    And the init skill loads the new rules into the session that ran it

  Scenario: The skills tell Claude to give every link its own status and a source it can be checked against
    Then the read skill says "with the paper and section as `--source`"
    And the read skill says "Choose the status for each link on its own, never one for all"
    And the insight skill says "Give the paper and section as `source`"
    And the graph skill says "A verified link's source must name the document it was checked against"

  Scenario: The skills say what was searched and read, and where dated lists come from
    Then the read skill says "If you couldn't search a place"
    And the read skill says "means you searched and nothing turned up"
    And the read skill says "Mark any claim that rests on a part you didn't read as unverified"
    And the read skill says "A search by title is yours, not a link taken from the paper"
    And the add skill says "add that spelling with `update --alias`"
    And the add skill says "An author with no `authorId` is added by name only, and you say so in your reply"
    And the add skill says "If the alias is refused because another author already has that name, don't force it"
    And the scholar skill says "the script reports it at once instead of retrying"
    And the arxiv skill says "`--since` and `--until` limit the submission dates, both days included"
    And the arxiv skill says "`--all-sections` to list the subsections too"
    And the next skill says "use `scholar` `search` with `--year`"
    And the scholar skill says "`recommend` can't be limited to a period"

  Scenario: The read skill extracts everything with a role in the paper, and its authors
    Then the read skill says "the baselines it compares against, the models it runs, and the models it uses as judges"
    And the read skill says "A passing mention is a name with no role in this paper"
    And the read skill says "the systems it compares in its tables"
    And the read skill says "A paper read without `add` still gets its authors"
    And the read skill says "Never make up an author"
    And the add skill says "Never make up an author"
    And the read skill says "a paper with no authors"

  Scenario: The skills say how to rank without an API key, and to check what a search found before reading it
    Then the scholar skill says "all of their citation counts in one `batch` call"
    And the scholar skill says "so the queries decide what can appear"
    And the scholar skill says "a free `SEMANTIC_SCHOLAR_API_KEY` gives a better answer"
    And the scholar skill says "show early traction, not influence"
    And the arxiv skill says "`--brief` leaves out the abstracts"
    And the read skill says "check each one before reading any of them"
    And the read skill says "stop and ask the user whether to skip it or read it chapter by chapter"
    And the read skill says "Say whether a download count is for all time or for the last 30 days"
    And the next skill says "Check that each pick is a paper that fits"

  Scenario: The docs and the graph skill say which entity types each relation joins
    Then the documented relation table matches the rules the script enforces
    And the graph skill says "Each joins only some entity types"
    And the graph skill says "`authored-by` goes from a paper, method, model, dataset, or tool to an author or organisation"
    And the graph skill says "`cites` from a paper to a paper"
    And the graph skill says "`related-to` joins anything"
    And the graph skill says "`link` refuses other pairs and says which types fit"
    And the graph skill says "`validate` lists older links that break this rule"

  Scenario: Papers are always listed in the same table
    Then every place that lists papers uses the same paper-list table
    And the paper-list rule says what goes in each column
    And the arxiv skill says "Each result has `published` and `link`"
    And the scholar skill says "each paper in a result has a `link`"
    And the add skill says "with a `Route` column after `Note`"
    And the next skill says "with `Standing` and `Source` after `Note`"
    And the next skill says "use the counts from this `batch` call for both the `Citations` column and the rating"
    And the next skill says "If the call fails, follow the paper-list rule"
    And the next skill says "write `?` and say so, or, for a pick in the graph, use the saved count"

  Scenario: The skills keep each paper's citation counts and links up to date without being asked
    Then the read skill says "s2.py batch <ID> --with-references"
    And the read skill says "run `graph.py standing <file>`"
    And the add skill says "--with-references"
    And the add skill says "run `graph.py standing <file>`"
    And the next skill says "run `graph.py standing <file>`, so the counts are kept"
    And the recap skill says "graph.py standing-due <tmp>/ids.txt"
    And the recap skill says "s2.py batch --ids-file <tmp>/ids.txt --with-references"
    And the recap skill says "Run `graph.py standing <tmp>/counts.json` whether or not step 2 succeeded"
    And the recap skill says "without reading the ids yourself"

  Scenario: A failed citation step is reported, not dropped
    Then the read skill says "say so in this reply"
    And the read skill says "Carry on with the other papers"
    And the read skill says "offer to retry the ones that failed"
    And the read skill says "links only connect papers that are already in the graph"

  Scenario: Questions about what the user has are answered from the graph too
    Then the rules written by init send questions about existing notes to the graph

  Scenario: The documentation agrees with init on when the new rules load
    Then the documentation says the new rules load in the session that ran init

  Scenario: Claude never writes its own permissions
    Then the init skill has the user run the write step
    And the troubleshooting page explains the auto mode block

  Scenario: No outside code is needed to run it
    Then the scripts import only the Python standard library

  Scenario: Scripts only talk to the hosts the README promises
    Then the scripts name only these hosts: arxiv.org, export.arxiv.org, www.arxiv.org, api.semanticscholar.org, www.semanticscholar.org, huggingface.co, doi.org, dx.doi.org, www.w3.org, purl.org, a9.com

  Scenario: The recap page works offline
    Then the page loads only files shipped next to it

  Scenario: The documentation points only to things that exist
    Then every link in the docs points to a file and heading that exist

  Scenario: The documentation covers every skill
    Then the docs describe every skill

  Scenario: The command reference covers every command
    Then the command reference lists every command of graph
    And the command reference lists every command of arxiv
    And the command reference lists every command of scholar
    And the command reference lists every option of init
