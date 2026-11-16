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

  Scenario: Invisible characters are removed from a paper's text, and the user is told
    Given Semantic Scholar then answers with a paper titled "Safe [U+202E]title" whose abstract reads "Real abstract.[U+E0069][U+E0067][U+E006E][U+E006F][U+E0072][U+E0065]"
    When I run scholar paper 1706.03762
    Then the command succeeds
    And the output holds no hidden characters
    And the printed paper is titled "Safe title"
    And the printed paper has the abstract "Real abstract."
    And the printed paper has the summary "Short summary" and the author "Ann Author"
    And the error mentions "removed 9 invisible character(s)"
    And the error mentions "6 of them were tag characters or variation selectors"
    And the error mentions "prompt-injection"

  Scenario: Stray invisible characters from Semantic Scholar are reported with no alarm
    Given Semantic Scholar then answers with a paper titled "Safe [U+202E]title" whose abstract reads "Real abstract.[U+200B]"
    When I run scholar paper 1706.03762
    Then the command succeeds
    And the printed paper is titled "Safe title"
    And the error mentions "removed 4 invisible character(s)"
    And the error does not mention "prompt-injection"

  Scenario Outline: Every command cleans what it prints
    Given Semantic Scholar then answers <answer>
    When I run scholar <command>
    Then the command succeeds
    And the output holds no hidden characters
    And the error mentions "removed <removed> invisible character(s)"
    And the error mentions "<tags> of them were tag characters or variation selectors"

    Examples:
      | answer                                                         | command                                | removed | tags |
      | a search with a paper titled "Ti[U+200B]tle[U+E0041]"          | search agents                          | 2       | 1    |
      | a recommendation with a paper titled "Ti[U+E0041][U+E0042]tle" | recommend --like ARXIV:2401.00001      | 2       | 2    |
      | about an author named "An[U+2060]n[U+E0042]"                   | authors 1                              | 2       | 1    |
      | with 3 papers titled "Ti[U+E0041]tle"                          | batch 2401.00001 2401.00002 2401.00003 | 3       | 3    |

  Scenario: A search result is printed without the hidden characters
    Given Semantic Scholar then answers a search with a paper titled "Safe [U+202E]title[U+E0041]"
    When I run scholar search agents
    Then the command succeeds
    And the first search result is titled "Safe title"

  Scenario: A failed request in a long list prints the papers already fetched, cleaned
    Given a file "ids.txt" of 501 arXiv ids
    And Semantic Scholar then answers with 500 papers titled "One[U+E0041]"
    And Semantic Scholar answers with HTTP 404
    When I look up the papers listed in "ids.txt"
    Then the command exits with code 1
    And the error mentions "500 of 501 papers"
    And the error mentions "removed 500 invisible character(s)"
    And 500 results are printed
    And the output holds no hidden characters

  Scenario: Text from Semantic Scholar with nothing hidden prints no note
    Given Semantic Scholar then answers with the paper "Attention Is All You Need"
    When I run scholar paper 1706.03762
    Then the command succeeds
    And nothing is written to the error output

  Scenario: A busy service is retried after a wait
    Given Semantic Scholar answers with HTTP 429
    And Semantic Scholar answers with HTTP 429
    And Semantic Scholar then answers with the paper "Attention Is All You Need"
    When I run scholar paper 1706.03762
    Then the command succeeds
    And Semantic Scholar was asked 3 times
    And the script waited before asking again

  Scenario: Without an API key, a refused search is reported at once so arXiv search can take over
    Given no Semantic Scholar API key is set
    And Semantic Scholar answers with HTTP 429
    When I run scholar search "agent memory"
    Then the command exits with code 1
    And Semantic Scholar was asked 1 times
    And the error mentions "use the arxiv skill's search instead"

  Scenario: Without an API key, other requests are still retried
    Given no Semantic Scholar API key is set
    And Semantic Scholar answers with HTTP 429
    And Semantic Scholar then answers with the paper "Attention Is All You Need"
    When I run scholar paper 1706.03762
    Then the command succeeds
    And Semantic Scholar was asked 2 times

  Scenario: Without an API key, a search that meets a server error is still retried
    Given no Semantic Scholar API key is set
    And Semantic Scholar answers with HTTP 503
    And Semantic Scholar then answers a search with a paper that has the arXiv id 2401.00001
    When I run scholar search "agent memory"
    Then the command succeeds
    And Semantic Scholar was asked 2 times

  Scenario: With an API key, a refused search is retried
    Given a Semantic Scholar API key is set
    And Semantic Scholar answers with HTTP 429
    And Semantic Scholar then answers a search with a paper that has the arXiv id 2401.00001
    When I run scholar search "agent memory"
    Then the command succeeds
    And Semantic Scholar was asked 2 times

  Scenario: A paper that does not exist is not retried
    Given Semantic Scholar answers with HTTP 404
    When I run scholar paper 1706.03762
    Then the command exits with code 1
    And Semantic Scholar was asked 1 times

  Scenario: A long result can be saved to a file in research instead of printed
    Given Semantic Scholar then answers a batch with a paper that has the arXiv id 2401.00006 and a DOI
    And I am in a workspace
    When I run scholar batch 2401.00001 --out WORKSPACE/research/found.json
    Then the command succeeds
    And only the path of "research/found.json" is printed
    And the file "research/found.json" holds 1 papers

  Scenario Outline: Every command refuses a path outside research before asking Semantic Scholar
    Given I am in a workspace
    When I run scholar <command> --out WORKSPACE/CLAUDE.md
    Then the command exits with code 2
    And the error mentions "--out must name a file inside"
    And Semantic Scholar was asked 0 times

    Examples:
      | command                  |
      | search "agent memory"    |
      | paper 1706.03762         |
      | batch 2401.00001         |
      | recommend --like 1706.03762 |
      | authors 12345            |

  Scenario Outline: Another project's control files in the temporary folder are never written
    Given I am in a workspace
    And a temporary folder outside the workspace
    When I run scholar batch 2401.00001 --out <path>
    Then the command exits with code 2
    And the error mentions "never CLAUDE.md, .mcp.json, lessons.md, profile.md, or a file inside .claude/ or .git/"
    And Semantic Scholar was asked 0 times

    Examples:
      | path                              |
      | ELSEWHERE/repo/CLAUDE.md          |
      | ELSEWHERE/repo/claude.MD          |
      | ELSEWHERE/repo/.mcp.json          |
      | ELSEWHERE/repo/.claude/settings.json |
      | ELSEWHERE/repo/.git/config        |

  Scenario Outline: Only .json and .txt files are written in the temporary folder
    Given I am in a workspace
    And a temporary folder outside the workspace
    When I run scholar batch 2401.00001 --out <path>
    Then the command exits with code 2
    And the error mentions "(a .json or .txt file there)"
    And Semantic Scholar was asked 0 times

    Examples:
      | path                               |
      | ELSEWHERE/repo/scripts/tool.py     |
      | ELSEWHERE/repo/README.md           |
      | ELSEWHERE/repo/Makefile            |
      | ELSEWHERE/repo/ci.yml              |

  Scenario Outline: A result is never saved outside research or over a file that steers Claude
    Given I am in a workspace
    When I run scholar batch 2401.00001 --out <path>
    Then the command exits with code 2
    And the error mentions "--out must name a file inside"
    And Semantic Scholar was asked 0 times

    Examples:
      | path                              |
      | WORKSPACE/CLAUDE.md               |
      | WORKSPACE/.claude/settings.json   |
      | WORKSPACE/research/lessons.md     |
      | WORKSPACE/research/profile.md     |
      | WORKSPACE/research/LESSONS.md     |
      | WORKSPACE/research/Profile.MD     |

  Scenario Outline: Each paper carries the link to show in the ID column of a paper list
    Given Semantic Scholar then answers a batch with a paper that has <ids>
    When I run scholar batch 2401.00001
    Then the command succeeds
    And the first printed result links to "<link>"

    Examples:
      | ids                                    | link                                                              |
      | the arXiv id 2401.00006 and a DOI      | [ARXIV:2401.00006](https://arxiv.org/abs/2401.00006)              |
      | only the DOI 10.1145/3442188.3445922   | [DOI:10.1145/3442188.3445922](https://doi.org/10.1145/3442188.3445922) |
      | no arXiv id or DOI                     | https://www.semanticscholar.org/paper/abc                         |

  Scenario: Search results carry links too
    Given Semantic Scholar then answers a search with a paper that has the arXiv id 2401.00006
    When I run scholar search "agent memory"
    Then the command succeeds
    And the first search result links to "[ARXIV:2401.00006](https://arxiv.org/abs/2401.00006)"

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
