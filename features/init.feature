Feature: Setting up a workspace without touching what the user already has
  As someone installing the plugin
  I want init to prepare my workspace and show me what it changes
  So that I can trust it with a folder that already has my own notes and settings

  Scenario: A new workspace gets everything it needs
    When I run init
    Then the command succeeds
    And the workspace has the starter research files
    And the workspace has the plugin's rules in CLAUDE.md
    And CLAUDE.md tells Claude to list papers in the paper-list table
    And Claude asks before fetching from arxiv.org
    And Claude asks before fetching from api.semanticscholar.org
    And the settings say nothing about fetching from example.com
    And the settings allow nothing
    And the local settings file is ignored by git

  Scenario: A dry run shows the changes and writes nothing
    When I run init as a dry run
    Then the command succeeds
    And the output mentions "create CLAUDE.md"
    And the output mentions "nothing written (dry run)"
    And the file "CLAUDE.md" does not exist
    And the file "research/papers.md" does not exist

  Scenario: Running init again changes nothing
    Given the file "x.txt" contains the text "x"
    When I run init
    And I run init
    Then the output mentions "workspace is up to date"

  Scenario: Existing notes and research files are never overwritten
    Given the file "research/papers.md" contains the text "my own list"
    And the file "CLAUDE.md" contains the text "# My project\n\nMy topics.\n"
    When I run init
    Then the command succeeds
    And the file "research/papers.md" contains "my own list"
    And CLAUDE.md still starts with "# My project"
    And the file "CLAUDE.md" contains "My topics."
    And the file "CLAUDE.md" contains "paper-research:begin"

  Scenario: Existing settings are kept and only extended
    Given the file ".claude/settings.json" contains the text "{\"permissions\": {\"allow\": [\"Bash(git *)\"]}, \"model\": \"sonnet\"}"
    When I run init
    Then the command succeeds
    And the settings keep "Bash(git *)" in the allow list
    And Claude asks before fetching from arxiv.org
    And the JSON file ".claude/settings.json" has "model" equal to "sonnet"

  Scenario: Updating the plugin refreshes only the rules block
    Given the file "CLAUDE.md" contains the text "before\n\n<!-- paper-research:begin (written by the init skill; edit outside this block) -->\nold rules\n<!-- paper-research:end -->\n\nafter\n"
    When I run init
    Then the file "CLAUDE.md" does not contain "old rules"
    And the file "CLAUDE.md" contains "before"
    And the file "CLAUDE.md" contains "after"

  Scenario: A settings file that cannot be read safely stops everything
    Given the file ".claude/settings.json" contains the text "{not json"
    When I run init
    Then the command exits with code 1
    And the error mentions "not valid JSON"
    And the file "research/papers.md" does not exist
    And the file "CLAUDE.md" does not exist

  Scenario: A half-written rules block stops everything
    Given the file "CLAUDE.md" contains the text "<!-- paper-research:end -->\n<!-- paper-research:begin (x) -->\n"
    When I run init
    Then the command exits with code 1
    And the error mentions "only one of the paper-research markers"
    And the file "research/papers.md" does not exist

  Scenario: Other skills and agents in the workspace can still use any tool
    When I run init
    Then the settings deny nothing

  Scenario: The sandbox is only turned on when asked for
    When I run init
    Then the settings do not turn the sandbox on
    When I run init with the sandbox
    Then the sandbox is on and limited to arxiv.org
    And the sandbox cannot reach "github.com"
    And the sandbox cannot reach "huggingface.co"

  Scenario: Changes to the files that steer Claude need my approval
    When I run init
    Then the settings ask before "Edit(/research/lessons.md)"
    And the settings ask before "Edit(/research/profile.md)"
    And the settings ask before "Edit(/CLAUDE.md)"
    And the settings ask before "Edit(/.claude/**)"

  Scenario: Every file the settings protect is a file init created
    When I run init with the sandbox
    Then every file the settings protect exists

  Scenario: The settings file keeps its own indentation
    Given the file ".claude/settings.json" contains the text "{\n    \"model\": \"sonnet\"\n}"
    When I run init
    Then line 2 of ".claude/settings.json" is "    \"model\": \"sonnet\","

  Scenario: The dry run shows the real file's lines, not a reformatted copy
    Given the file ".claude/settings.json" contains the text "{\n    \"model\": \"sonnet\"\n}"
    When I run init as a dry run
    Then the output mentions "-    \"model\": \"sonnet\""

  Scenario: Two rules blocks are not half-fixed
    Given the file "CLAUDE.md" contains the text "<!-- paper-research:begin (a) -->\n<!-- paper-research:end -->\n<!-- paper-research:begin (b) -->\n<!-- paper-research:end -->\n"
    When I run init
    Then the command exits with code 1
    And the error mentions "more than one paper-research block"
    And the file "research/papers.md" does not exist

  Scenario: Settings that could not be merged safely stop everything
    Given the file ".claude/settings.json" contains the text "{\"permissions\": {\"deny\": \"all\"}}"
    When I run init
    Then the command exits with code 1
    And the error mentions "unexpected shape"
