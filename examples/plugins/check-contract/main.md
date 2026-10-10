---
type: Playbook
name: check-contract
status: draft
requires: []
capabilities: [inspect-deliverable]
effects: [report-missing-required-fields]
invariants: [preserve-task-requirements, preserve-validation-evidence]
incompatible: [skip-required-checks]
---
# Verificar contrato

Plugin demonstrativo para revisar a presença de campos obrigatórios antes da entrega. Deve integrar o candidato antes da assinatura e requer revisão semântica da combinação.

## Pseudocode

WHEN preparing final delivery:
  READ the task's declared required fields.
  CALL the selected tier's validator with those fields.
  IF required fields are missing: repair and run the same checks again.
  IF evidence remains insufficient: report the limitation; do not claim success.
  PRESERVE original requirements, validation records and source references.

Veja [limites](limits.md).
