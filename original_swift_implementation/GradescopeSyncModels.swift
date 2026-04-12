import Foundation

public struct GradescopeCalendarEventSnapshot: Sendable {
    public let identifier: String
    public let title: String
    public let start: Date
    public let end: Date
    public let notes: String?
    public let tag: String

    public init(
        identifier: String,
        title: String,
        start: Date,
        end: Date,
        notes: String?,
        tag: String
    ) {
        self.identifier = identifier
        self.title = title
        self.start = start
        self.end = end
        self.notes = notes
        self.tag = tag
    }
}

/// GradescopeSyncRequest — contract for GradescopeSyncService.planSync(request:)
/// Last modified: 2026-03-27 — extracted explicit Gradescope assignment/calendar comparison input
public struct GradescopeSyncRequest: Sendable {
    public let calendarName: String
    public let assignments: [GradescopeAssignment]
    public let existingEvents: [GradescopeCalendarEventSnapshot]

    public init(
        calendarName: String,
        assignments: [GradescopeAssignment],
        existingEvents: [GradescopeCalendarEventSnapshot]
    ) {
        self.calendarName = calendarName
        self.assignments = assignments
        self.existingEvents = existingEvents
    }
}

public enum GradescopeSyncOperation: Sendable, Equatable {
    case create(GradescopeCalendarMutation)
    case update(GradescopeCalendarMutation)
}

public struct GradescopeCalendarMutation: Sendable, Equatable {
    public let tag: String
    public let title: String
    public let start: Date
    public let end: Date
    public let notes: String
    public let existingEventIdentifier: String?

    public init(
        tag: String,
        title: String,
        start: Date,
        end: Date,
        notes: String,
        existingEventIdentifier: String? = nil
    ) {
        self.tag = tag
        self.title = title
        self.start = start
        self.end = end
        self.notes = notes
        self.existingEventIdentifier = existingEventIdentifier
    }
}

/// GradescopeSyncResult — contract for GradescopeSyncService.planSync(request:)
/// Last modified: 2026-03-27 — made sync planning return typed calendar mutations
public struct GradescopeSyncResult: Sendable, Equatable {
    public let calendarName: String
    public let operations: [GradescopeSyncOperation]

    public init(
        calendarName: String,
        operations: [GradescopeSyncOperation]
    ) {
        self.calendarName = calendarName
        self.operations = operations
    }
}
