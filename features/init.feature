Feature: Setting up a workspace, and the rules and approval prompts the plugin brings to it
  As someone installing the plugin
  I want one command to prepare my folder, and the plugin to load its rules and guard its files on its own
  So that I never have to edit my settings or run a command myself, and nothing I already have is changed

  Scenario: A new workspace gets its starter files and the rules at once
    When I run init
    Then the command succeeds
    And the workspace has the starter research files
    And the output mentions "created research/papers.md"
    And the output holds the plugin's rules and the lessons
    And the local settings file is ignored by git

  Scenario: Setting up never touches CLAUDE.md, the settings, or existing notes
    Given the file "research/papers.md" contains the text "my own list"
    And the file "CLAUDE.md" contains the text "# My project\n"
    And the file ".claude/settings.json" contains the text "{\"model\": \"sonnet\"}"
    When I run init
    Then the command succeeds
    And the file "research/papers.md" contains "my own list"
    And the file "CLAUDE.md" is still "# My project\n"
    And the file ".claude/settings.json" is still "{\"model\": \"sonnet\"}"

  Scenario: Running init again creates nothing
    When I run init
    And I run init
    Then the output does not mention "created "
    And the output does not mention "updated "

  Scenario: A session in a workspace starts with the rules and the lessons
    Given a workspace just set up by init
    And the file "research/lessons.md" contains the text "# Lessons\n\n- Answer in one table.\n"
    When a session starts in the workspace
    Then Claude is given the plugin's rules
    And Claude is given the lessons, including "- Answer in one table."

  Scenario: A session in another folder gets nothing from the plugin
    When a session starts in the workspace
    Then Claude is given nothing by the plugin

  Scenario Outline: Changing the files that later sessions follow needs my approval
    Given a workspace just set up by init
    When Claude uses <tool> on "<path>"
    Then I am asked to approve it, because of "<file>"

    Examples:
      | tool         | path                | file                |
      | Edit         | research/lessons.md | research/lessons.md |
      | Write        | research/profile.md | research/profile.md |
      | MultiEdit    | research/lessons.md | research/lessons.md |
      | NotebookEdit | research/profile.md | research/profile.md |

  Scenario Outline: Other files are left to Claude Code
    Given a workspace just set up by init
    When Claude uses Edit on "<path>"
    Then the tool call goes ahead without a prompt from the plugin

    Examples:
      | path                  |
      | research/pins.md      |
      | research/insights.md  |
      | CLAUDE.md             |
      | .claude/settings.json |

  Scenario Outline: Fetching from the plugin's hosts needs my approval
    Given a workspace just set up by init
    When Claude fetches "<url>"
    Then I am asked to approve it, because of "<host>"

    Examples:
      | url                                       | host                    |
      | https://arxiv.org/abs/2401.00001          | arxiv.org               |
      | https://export.arxiv.org/api/query        | export.arxiv.org        |
      | https://api.semanticscholar.org/graph/v1/ | api.semanticscholar.org |
      | https://huggingface.co/papers             | huggingface.co          |
      | https://github.com/some/repo              | github.com              |
      | https://api.github.com/repos/some/repo    | api.github.com          |

  Scenario: Fetching from another site is left to Claude Code
    Given a workspace just set up by init
    When Claude fetches "https://example.com/"
    Then the tool call goes ahead without a prompt from the plugin

  Scenario: Outside a workspace the plugin never asks
    When Claude uses Edit on "research/lessons.md"
    Then the tool call goes ahead without a prompt from the plugin
    When Claude fetches "https://arxiv.org/abs/2401.00001"
    Then the tool call goes ahead without a prompt from the plugin

  Scenario Outline: Other spellings of a guarded file still ask
    Given a workspace just set up by init
    When Claude uses Edit on "<path>"
    Then I am asked to approve it, because of "research/lessons.md"

    Examples:
      | path                              |
      | research/../research/lessons.md   |
      | ./research/./lessons.md           |
      | research/LESSONS.MD               |
      | research/lessons.md.              |
      | research/lessons.md::$DATA        |
      | notes/../research/lessons.md      |

  Scenario: Another name for the same file still asks
    Given a workspace just set up by init
    And "notes.md" is a link to "research/lessons.md"
    When Claude uses Edit on "notes.md"
    Then I am asked to approve it, because of "research/lessons.md"

  Scenario Outline: Other spellings of a plugin host still ask, and look-alikes don't
    Given a workspace just set up by init
    When Claude fetches "<url>"
    Then <outcome>

    Examples:
      | url                            | outcome                                                  |
      | https://ARXIV.ORG/abs/1        | I am asked to approve it, because of "arxiv.org"         |
      | https://user@arxiv.org./abs/1  | I am asked to approve it, because of "arxiv.org"         |
      | https://%61rxiv.org/abs/1      | I am asked to approve it, because of "arxiv.org"         |
      | https://arxiv.org@evil.com/    | the tool call goes ahead without a prompt from the plugin |
      | https://arxiv.org.evil.com/    | the tool call goes ahead without a prompt from the plugin |
      | https://evilarxiv.org/         | the tool call goes ahead without a prompt from the plugin |

  Scenario: A tool call the plugin can't read asks rather than letting it through
    Given a workspace just set up by init
    When Claude uses Edit with the input "{\"file_path\": 5}"
    Then I am asked to approve it, because of "couldn't tell"

  Scenario Outline: A broken event never stops Claude
    Given a workspace just set up by init
    When the <hook> hook is sent "<event>"
    Then the command succeeds
    And nothing is written to the error output

    Examples:
      | hook    | event      |
      | rules   | {not json  |
      | lessons | [1, 2]     |
      | guard   | {not json  |
      | guard   | "text"     |

  Scenario Outline: The registered approval hook asks whichever Python the system has
    Given a workspace just set up by init
    When the registered approval hook runs before an edit to the lessons, with python3 <python3>
    Then I am asked to approve it, because of "research/lessons.md"

    Examples:
      | python3                       |
      | working                       |
      | missing                       |
      | failing                       |
      | only the Windows Store alias  |
