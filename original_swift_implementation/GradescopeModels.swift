import Foundation

// MARK: - Course

public struct GradescopeCourse: Sendable {
    public let id: String
    public let name: String
    public let shortName: String
    public let term: String
    public let year: String

    public var termYear: String { "\(term) \(year)" }
}

// MARK: - Assignment

public enum GradescopeSubmissionStatus: String, Sendable {
    case unsubmitted
    case submitted
    case graded
}

public struct GradescopeAssignment: Sendable {
    public let id: String
    public let courseId: String
    public let courseName: String
    public let name: String
    public let status: GradescopeSubmissionStatus
    public let releasedAt: Date?
    public let dueAt: Date?
    public let lateDueAt: Date?

    public var url: URL {
        URL(string: "https://www.gradescope.com/courses/\(courseId)/assignments/\(id)")!
    }

    /// Stable tag embedded in calendar event notes to identify this assignment.
    /// Used for deduplication across sync cycles.
    public var calendarTag: String {
        "gs-assignment-id:\(id)@\(courseId)"
    }

    public var isUpcoming: Bool {
        guard let due = dueAt else { return false }
        return due > Date()
    }
}
