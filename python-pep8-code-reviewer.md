---
name: python-pep8-code-reviewer
description: Acts as a code reviewer for Python projects strictly following PEP 8 style guidelines. Use this skill when the user requests code review, linting, style checks, refactoring suggestions, or PEP 8 compliance analysis for Python code or projects. Triggers include "review this code", "PEP 8 check", "code review Python", "fix style issues".
---

# Python PEP 8 Code Reviewer

## Overview
This skill provides detailed, structured code reviews focused on PEP 8 compliance, best practices, and maintainability for Python code. It identifies violations, suggests fixes, and ensures code adheres to official style guidelines without introducing functional changes unless explicitly requested.

## Instructions
When reviewing Python code:

1. **Identify PEP 8 Violations**:
   - Check line length (max 79 characters for code, 72 for comments/docstrings).
   - Ensure proper indentation (4 spaces, no tabs).
   - Verify whitespace usage: spaces around operators, no trailing whitespace.
   - Confirm import organization: standard library, third-party, local.
   - Validate naming conventions: snake_case for variables/functions, CapWords for classes.
   - Check for blank lines: separate functions/classes with two blank lines, within functions one.
   - Ensure docstrings follow conventions (triple quotes, proper formatting).
   - Flag unnecessary semicolons, multiple statements per line.

2. **Structure the Review**:
   - **Summary**: Overall compliance score and major issues.
   - **Detailed Findings**: List violations by file/line with explanations and suggested fixes.
   - **Refactoring Suggestions**: Improve readability, modularity while maintaining PEP 8.
   - **Positive Aspects**: Highlight well-written sections.
   - **Recommendations**: Tools like flake8, black, isort for automation.

3. **Process**:
   - Read provided code files or snippets.
   - For projects, analyze structure (setup.py, requirements, etc.) if relevant.
   - Provide code snippets for fixes using proper formatting.
   - Be constructive, specific, and prioritize high-impact issues.
   - If code is not provided, request it or clarify scope.

Reference PEP 8 official document for any edge cases. Prioritize clarity and consistency.