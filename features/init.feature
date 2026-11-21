Feature: Setting up a workspace, and the rules and approval prompts the plugin brings to it
  As someone installing the plugin
  I want one command to prepare my folder, and the plugin to load its rules and guard its files on its own
  So that I never have to edit my settings or run a command myself, and nothing I already have is changed

  Scenario: Setting up keeps my files, and every later session gets the rules and guards the lessons
    Given the file "CLAUDE.md" contains the text "# My project\n"
    And the file "research/lessons.md" contains the text "# Lessons\n\n- Answer in one table.\n"
    When I run init
    Then the command succeeds
    And the workspace has the starter research files
    And the file "CLAUDE.md" is still "# My project\n"
    When a session starts in the workspace
    Then Claude is given the plugin's rules
    And Claude is given the lessons, including "- Answer in one table."
    When Claude uses Edit on "research/lessons.md"
    Then I am asked to approve it, because of "research/lessons.md"
    When Claude uses Edit on "research/pins.md"
    Then the tool call goes ahead without a prompt from the plugin
