Feature: Paper details and citations from Semantic Scholar
  As a reader
  I want paper metadata and citation links even when the service is busy
  So that recommendations and the graph can rest on real data

  Background:
    Given Semantic Scholar answers can be scripted

  Scenario: Getting a paper
    Given Semantic Scholar then answers with the paper "Attention Is All You Need"
    When I run scholar paper 1706.03762
    Then the command succeeds
    And the printed paper is titled "Attention Is All You Need"
    And every request went to the Semantic Scholar API host
    And no request carried an API key

  Scenario: A busy service is retried after a wait
    Given Semantic Scholar answers with HTTP 429
    And Semantic Scholar answers with HTTP 429
    And Semantic Scholar then answers with the paper "Attention Is All You Need"
    When I run scholar paper 1706.03762
    Then the command succeeds
    And Semantic Scholar was asked 3 times
    And the script waited before asking again

  Scenario: A paper that does not exist is not retried
    Given Semantic Scholar answers with HTTP 404
    When I run scholar paper 1706.03762
    Then the command exits with code 1
    And Semantic Scholar was asked 1 times

  Scenario: A batch marks the papers it could not find
    Given Semantic Scholar then answers with an unknown paper
    When I run scholar batch 2401.00001
    Then the command succeeds
    And the first printed result says "not found"

  Scenario: A long list of papers in a file goes out 500 at a time
    Given a file "ids.txt" of 501 arXiv ids
    And Semantic Scholar then answers with 500 unknown papers
    And Semantic Scholar then answers with 1 unknown papers
    When I look up the papers listed in "ids.txt"
    Then the command succeeds
    And Semantic Scholar was asked 2 times
    And 501 results are printed

  Scenario: Reference lists are asked for 100 papers at a time
    Given a file "ids.txt" of 201 arXiv ids
    And Semantic Scholar then answers with 100 unknown papers
    And Semantic Scholar then answers with 100 unknown papers
    And Semantic Scholar then answers with 1 unknown papers
    When I look up the papers listed in "ids.txt" with their references
    Then the command succeeds
    And Semantic Scholar was asked 3 times
    And every request asked for the reference lists
    And 201 results are printed

  Scenario: A failed request in a long list keeps the papers already fetched
    Given a file "ids.txt" of 501 arXiv ids
    And Semantic Scholar then answers with 500 unknown papers
    And Semantic Scholar answers with HTTP 404
    When I look up the papers listed in "ids.txt"
    Then the command exits with code 1
    And the error mentions "500 of 501 papers"
    And 500 results are printed

  Scenario: A batch with no ids is refused before any request
    When I run scholar batch
    Then the command exits with code 2
    And the error mentions "give at least one"
    And Semantic Scholar was asked 0 times

  Scenario: An unexpected answer is reported, not guessed at
    Given Semantic Scholar then answers with something unexpected
    When I run scholar batch 2401.00001
    Then the command exits with code 1
    And the error mentions "unexpected response"

  Scenario: Out-of-range limits are refused before any request
    When I run scholar search "agents" --limit 500
    Then the command exits with code 2
    And the error mentions "must be between"
    And Semantic Scholar was asked 0 times

  Scenario: Author ids must be plain digits
    When I run scholar authors 12²
    Then the command exits with code 2
    And Semantic Scholar was asked 0 times
