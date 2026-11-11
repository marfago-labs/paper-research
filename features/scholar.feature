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
