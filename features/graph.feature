Feature: A knowledge graph that stays trustworthy as it grows
  As a reader who adds papers every day
  I want the graph to catch duplicates and refuse bad edits
  So that the connections between papers can be relied on

  Background:
    Given an empty graph

  Scenario: A possible duplicate is held until someone decides, and the decision is remembered
    Given the graph has a dataset "Terminal-Bench 2.1"
    And the graph holds a paper "Paper X" with id "paper:2401.00003"
    When I run graph add --type dataset --name "Terminal-Bench 2.0" --link-from paper:2401.00003 evaluates-on --source "ARXIV:2401.00003, section 4" --status verified
    Then the command exits with code 3
    And the error mentions "possible duplicates"
    And the error mentions "dataset:terminal-bench-2-1"
    And the graph has 0 relations
    When I run graph add --type dataset --name "Terminal-Bench 2.0" --distinct "Terminal-Bench 2.1" --link-from paper:2401.00003 evaluates-on --source "ARXIV:2401.00003, section 4" --status verified
    Then the command succeeds
    And the graph has the relation "paper:2401.00003" evaluates-on "dataset:terminal-bench-2-0"
    When I run graph dupes
    Then the output mentions "no likely duplicates"

  Scenario: Validation lists a link that needs fixing without blocking the graph, and passes once it is fixed
    Given the graph holds a paper "Paper X" with id "paper:2401.00003"
    And the graph holds a paper "Paper N" with id "paper:2401.00004"
    And every paper in the graph has the author "Ann Lee"
    And a verified link "paper:2401.00003" related-to "paper:2401.00004" has the source "Same group"
    When I run graph validate
    Then the command fails
    And the output mentions "found 1 verified link with no document it was checked against"
    And the output mentions "unlink it and link it again"
    When I run graph stats
    Then the command succeeds
    When I run graph unlink paper:2401.00003 related-to paper:2401.00004
    And I run graph link paper:2401.00003 related-to paper:2401.00004 --source "Same group" --status inferred
    And I run graph validate
    Then the command succeeds
    And the output mentions "OK: 3 entities, 3 relations"

  Scenario: Citation counts are saved with their date, shown in search, and not asked for again until due
    Given the graph holds a paper "Paper A" with id "paper:2611.00001"
    When I run graph standing-due research/due.txt
    Then the output mentions "1 paper due"
    And the file "research/due.txt" contains "ARXIV:2611.00001"
    Given Semantic Scholar's batch output in "s2.json" gives ARXIV:2611.00001 42 citations
    When I run graph standing s2.json
    Then the command succeeds
    And the paper "paper:2611.00001" has 42 citations checked today
    When I run graph search 2611.00001
    Then the output mentions "42 citations, checked"
    When I run graph standing-due research/due.txt
    Then the output mentions "no papers due"

  Scenario: A paper with no author to record says why, and then passes validation
    Given the graph holds a paper "Anonymous submission" with id "paper:2401.00005"
    When I run graph validate
    Then the command fails
    And the output mentions "found 1 paper with no authors"
    And the output mentions "say why with update --no-authors REASON"
    When I run graph update paper:2401.00005 --no-authors "anonymous submission under review"
    Then the command succeeds
    When I run graph validate
    Then the command succeeds
    And the output mentions "1 paper with a reason instead of authors"
