
# Spec-Driven Development Methodology

## Overview

This document defines my preferred approach to spec-driven development using Copilot. When I request "spec-driven development" for a project, follow this structured methodology.

## Phase 1: Requirements Gathering

When starting spec-driven development:

1. **Requirements Document**
   - Create a comprehensive requirements.md file
   - Include functional and non-functional requirements using user stories
   - Write stories in "As a [user], I want [goal] so that [benefit]" format
   - Define success criteria, constraints, and acceptance criteria
   - Identify target users and use cases

## Phase 2: Design Specifications

2. **Design Document**
   - Create design.md with system architecture and technical approach
   - Define component interactions and data flow
   - Specify technology stack and infrastructure requirements
   - Include security, scalability, and implementation considerations
   - Document architectural decisions and their rationales

## Phase 3: Implementation Planning

3. **Implementation Tasks**
   - Generate tasks.md with specific development tasks
   - Break down requirements and design in to actionable development work
   - Include estimates, dependencies, and completion criteria
   - Organize tasks by priority and implementation sequence

## File Structure Standards

When creating spec-driven projects, organize files as:

```
project-name/
├── .bk/
│   └── specs/
│       └── [feature-name]/
│           ├── requirements.md
│           ├── design.md
│           └── tasks.md
├── src/
└── tests/
```

## Documentation Standards

- Use clear, concise language in all specifications
- Include examples and use cases where helpful
- Maintain consistency in formatting and structure
- Update specifications as requirements evolve
- Link related documents and reference dependencies

## Development Workflow

1. Always start with requirements gathering before coding
2. Validate specifications with stakeholders before implementation
3. Use specifications to guide all development decisions
4. Update documentation as the project evolves
5. Reference specifications when debugging or adding features

## Quality Criteria

Specifications should be:

- **Complete**: Cover all functional and non-functional requirements
- **Consistent**: Use consistent terminology and patterns
- **Testable**: Include criteria that can be validated
- **Maintainable**: Easy to update as requirements change
- **Accessible**: Clear to both technical and non-technical stakeholders