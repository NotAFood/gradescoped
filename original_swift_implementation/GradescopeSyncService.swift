import Foundation
import os

public actor GradescopeSyncService {
    private let logger = Logger(subsystem: "one.cael.myelin", category: "gradescope-sync")

    public init() {}

    public func planSync(request: GradescopeSyncRequest) -> GradescopeSyncResult {
        let existingByTag = Dictionary(
            uniqueKeysWithValues: request.existingEvents.map { ($0.tag, $0) }
        )

        var operations: [GradescopeSyncOperation] = []

        for assignment in request.assignments {
            guard let dueAt = assignment.dueAt else {
                continue
            }

            let mutation = plannedMutation(for: assignment, existing: existingByTag[assignment.calendarTag])

            if let existing = existingByTag[assignment.calendarTag] {
                if existing.title != mutation.title || existing.start != mutation.start || existing.end != mutation.end || existing.notes != mutation.notes {
                    operations.append(.update(mutation))
                }
            } else {
                operations.append(.create(mutation))
            }
        }

        logger.info(
            "Gradescope sync planned \(operations.count, privacy: .public) operations for \(request.assignments.count, privacy: .public) assignments"
        )
        return GradescopeSyncResult(calendarName: request.calendarName, operations: operations)
    }

    private func plannedMutation(
        for assignment: GradescopeAssignment,
        existing: GradescopeCalendarEventSnapshot?
    ) -> GradescopeCalendarMutation {
        let dueAt = assignment.dueAt ?? Date()
        let title = "[\(assignment.courseName)] \(assignment.name)"
        let notes = "\(assignment.url.absoluteString)\n\(assignment.calendarTag)"
        let start = dueAt.addingTimeInterval(-3600)
        let end = dueAt

        return GradescopeCalendarMutation(
            tag: assignment.calendarTag,
            title: title,
            start: start,
            end: end,
            notes: notes,
            existingEventIdentifier: existing?.identifier
        )
    }
}
