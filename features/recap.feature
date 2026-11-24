Feature: A recap page that shows what has been done so far
  As a reader who works across several sessions
  I want one page with my papers, insights, everything I told Claude, and graph
  So that I can see my progress and what still needs doing

  Scenario: A turn that changed the research files ends only after the recap is refreshed
    Given a workspace just set up by init
    When the turn ends
    Then the turn is allowed to end
    Given the user added the pin "Critic loop"
    When the turn ends
    Then Claude is told to refresh the recap and log the questions
    When the recap page is refreshed
    Then the recap folder holds the page, its script library, and the data
    When the turn ends
    Then the turn is allowed to end

  Scenario: A paper read in part is flagged until something is extracted from it, and a status that is out of date is found
    Given a workspace just set up by init
    And the reading list holds "Paper A" as ARXIV:2611.00001 with the status partial
    And the reading list holds "Paper B" as ARXIV:2611.00002 with the status skim
    And the reading list holds "Paper C" as ARXIV:2611.00003 with the status read
    And the reading list holds "Paper D" as ARXIV:2611.00004 with the status done
    And the graph holds a paper "Paper A" with id "paper:2611.00001"
    And the graph holds a paper "Paper B" with id "paper:2611.00002"
    And the graph holds a paper "Paper C" with id "paper:2611.00003"
    And the graph holds a paper "Paper D" with id "paper:2611.00004"
    When I run graph add --type concept --name "Tool selection" --link-from paper:2611.00002 proposes --source "ARXIV:2611.00002, section 2" --status verified
    Then the command succeeds
    # Paper B was read, and builds on papers C and D, which nobody has opened: a link that points at a paper extracts nothing from it.
    When I run graph link paper:2611.00002 builds-on paper:2611.00003 --source "ARXIV:2611.00002, section 5" --status inferred
    And I run graph link paper:2611.00002 builds-on paper:2611.00004 --source "ARXIV:2611.00002, section 5" --status inferred
    Then the command succeeds
    When the recap page is refreshed
    Then the Activity tab counts 1 to read
    And the Activity tab counts 1 to skim
    And the Activity tab counts 1 read in part
    And the Activity tab lists "Paper A" under "Needs graph extraction"
    And the Activity tab lists "Paper B" under "Status out of date"
    And the Activity tab lists "Paper D" under "Needs graph extraction"
    And the Activity tab does not list "Paper C" under "Needs graph extraction"
    And the Activity tab does not list "Paper C" under "Status out of date"
    When I run graph add --type concept --name "Stepwise planning" --link-from paper:2611.00001 proposes --source "ARXIV:2611.00001, section 3" --status verified
    Then the command succeeds
    When the recap page is refreshed
    Then the Activity tab does not list "Paper A" under "Needs graph extraction"
    And the Activity tab counts 1 read in part
