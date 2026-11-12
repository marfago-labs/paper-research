Feature: A recap page that shows what has been done so far
  As a reader who works across several sessions
  I want one page with my papers, insights, questions, and graph
  So that I can see my progress and what still needs doing

  Scenario: An empty workspace shows an empty recap
    When I refresh the recap
    Then the command succeeds
    And the recap data lists 0 papers
    And the recap folder holds the page, its script library, and the data

  Scenario: Papers, insights, and questions appear with their links
    Given a research folder with these papers
      | added      | title      | id               | status  |
      | 2026-11-05 | First one  | ARXIV:2611.00001 | read    |
      | 2026-11-06 | Second one | ARXIV:2611.00002 | archive |
    And an insight "Keep reviewers read-only" drawn from ARXIV:2611.00001
    And the user asked "Does it use a critic?" on 2026-11-06
    When I refresh the recap
    Then the recap data lists 2 papers
    And the recap data links the insight to ARXIV:2611.00001
    And the recap data has the question "Does it use a critic?"

  Scenario: A paper with only its authors in the graph is flagged as needing extraction
    Given a research folder with these papers
      | added      | title     | id               | status |
      | 2026-11-05 | Read this | ARXIV:2611.00001 | read   |
      | 2026-11-05 | And this  | ARXIV:2611.00002 | read   |
    And the graph has the paper "2611.00001" with only its author
    When I refresh the recap
    Then the recap data marks ARXIV:2611.00001 as "unextracted"
    And the recap data marks ARXIV:2611.00002 as "missing"

  Scenario: Each paper shows its citations and how often it comes up in my collection
    Given a research folder with these papers
      | added      | title     | id               | status |
      | 2026-11-05 | Cited     | ARXIV:2611.00001 | read   |
      | 2026-11-06 | Citing    | ARXIV:2611.00002 | read   |
    And the graph has the paper "2611.00001" with 42 citations, cited by the paper "2611.00002"
    And an insight "Keep reviewers read-only" drawn from ARXIV:2611.00001
    When I refresh the recap
    Then the recap data gives ARXIV:2611.00001 42 citations
    And the recap data says ARXIV:2611.00001 is cited by 1 of my papers, in 1 insight, and in 0 pins
    And the recap data has no citation counts for ARXIV:2611.00002

  Scenario: A paper with extracted entities is not flagged
    Given a research folder with these papers
      | added      | title     | id               | status |
      | 2026-11-05 | Read this | ARXIV:2611.00001 | read   |
    And the graph has the paper "2611.00001" with a dataset it evaluates on
    When I refresh the recap
    Then the recap data marks ARXIV:2611.00001 as "extracted"

  Scenario: A saved full text that papers.md does not list is flagged as not in the graph
    Given the full text of "2611.00003" is saved
    When I refresh the recap
    Then the recap data lists 1 papers
    And the recap data marks ARXIV:2611.00003 as "missing"

  Scenario: A saved full text that is already in the graph is flagged as extracted
    Given the full text of "2611.00003" is saved
    And the graph has the paper "2611.00003" with a dataset it evaluates on
    When I refresh the recap
    Then the recap data marks ARXIV:2611.00003 as "extracted"

  Scenario Outline: A saved full text is not listed twice when papers.md writes its id differently
    Given a research folder with these papers
      | added      | title     | id   | status |
      | 2026-11-05 | Read this | <id> | read   |
    And the full text of "2611.00003" is saved
    When I refresh the recap
    Then the recap data lists 1 papers

    Examples:
      | id                                 |
      | ARXIV:2611.00003                   |
      | ARXIV:2611.00003v2                 |
      | arXiv:2611.00003                   |
      | https://arxiv.org/abs/2611.00003v3 |
      | https://arxiv.org/pdf/2611.00003   |

  Scenario: A different paper in papers.md does not hide a saved full text
    Given a research folder with these papers
      | added      | title     | id               | status |
      | 2026-11-05 | Read this | ARXIV:2611.00001 | read   |
    And the full text of "2611.00003" is saved
    When I refresh the recap
    Then the recap data lists 2 papers
    And the recap data marks ARXIV:2611.00003 as "missing"

  Scenario: Files in the full text folder that are not arXiv papers are ignored
    Given the full text of "notes" is saved
    And the full text of "hep-th-9901001" is saved
    When I refresh the recap
    Then the recap data lists 0 papers

  Scenario: A broken graph is reported but does not stop the recap
    Given a research folder with these papers
      | added      | title     | id               | status |
      | 2026-11-05 | Read this | ARXIV:2611.00001 | read   |
    And the file "research/graph/entities.jsonl" contains the text "{\"id\": \"tool:x\", \"type\": \"tool\", \"name\": \"X\", \"url\": 5}"
    And the file "research/graph/relations.jsonl" is empty
    When I refresh the recap
    Then the command succeeds
    And the error mentions "graph not shown"
    And the recap data says the graph cannot be shown because "url must be text"
    And the recap data has no graph status for ARXIV:2611.00001

  Scenario: Refreshing twice gives the same page
    When I refresh the recap
    And I refresh the recap
    Then the command succeeds
    And the recap folder holds the page, its script library, and the data
