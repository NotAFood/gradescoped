import Foundation
import os

// MARK: - Redirect cookie delegate

/// Captures cookies from a redirect response and optionally blocks the redirect.
/// Used for login: we want the cookies from the 302 but will follow the redirect manually.
private class LoginRedirectDelegate: NSObject, URLSessionTaskDelegate {
    private(set) var capturedCookies: [HTTPCookie] = []

    func urlSession(
        _ session: URLSession,
        task: URLSessionTask,
        willPerformHTTPRedirection response: HTTPURLResponse,
        newRequest request: URLRequest,
        completionHandler: @escaping (URLRequest?) -> Void
    ) {
        if let url = task.currentRequest?.url,
           let headers = response.allHeaderFields as? [String: String] {
            capturedCookies.append(contentsOf: HTTPCookie.cookies(withResponseHeaderFields: headers, for: url))
        }
        completionHandler(nil) // block redirect; we follow manually after storing cookies
    }
}

// MARK: - Errors

public enum GradescopeError: LocalizedError {
    case loginFailed
    case invalidCredentials
    case htmlParseError(String)
    case missingElement(String)
    case networkError(Error)

    public var errorDescription: String? {
        switch self {
        case .loginFailed: return "Gradescope login failed."
        case .invalidCredentials: return "Invalid Gradescope credentials."
        case .htmlParseError(let detail): return "HTML parse error: \(detail)"
        case .missingElement(let selector): return "Expected HTML element not found: \(selector)"
        case .networkError(let error): return "Network error: \(error.localizedDescription)"
        }
    }
}

// MARK: - Client

/// Scrapes Gradescope via its web interface, mirroring the Python GradescopeSync implementation.
public actor GradescopeClient {

    private static let baseURL = "https://www.gradescope.com"

    private let session: URLSession
    private var cookies: [HTTPCookie] = []
    private let logger = Logger(subsystem: "one.cael.myelin", category: "gradescope")

    // Gradescope datetime format: "2026-02-13 23:59:59 -0800" (RFC 822 offset in hidden-column <td>)
    private static let dateFormatter: DateFormatter = {
        let f = DateFormatter()
        f.dateFormat = "yyyy-MM-dd HH:mm:ss Z"
        f.locale = Locale(identifier: "en_US_POSIX")
        return f
    }()

    public init() {
        let config = URLSessionConfiguration.ephemeral
        config.httpShouldSetCookies = false      // we manage cookies manually
        config.httpCookieAcceptPolicy = .never
        self.session = URLSession(configuration: config)
    }

    // MARK: - Auth

    /// Authenticates with Gradescope. Must be called before fetching courses/assignments.
    public func login(email: String, password: String) async throws {
        // Step 1: GET home page to grab the authenticity_token CSRF value
        let homeData = try await get("/")
        let authToken = try extractAuthenticityToken(from: homeData)


        // Step 2: POST credentials as form body with browser-like headers
        let formFields: [(String, String)] = [
            ("utf8", "✓"),
            ("session[email]", email),
            ("session[password]", password),
            ("session[remember_me]", "0"),
            ("commit", "Log In"),
            ("session[remember_me_sso]", "0"),
            ("authenticity_token", authToken),
        ]
        let body = formEncode(formFields)

        var request = URLRequest(url: url(for: "/login"))
        request.httpMethod = "POST"
        request.setValue("application/x-www-form-urlencoded", forHTTPHeaderField: "Content-Type")
        request.setValue(Self.baseURL, forHTTPHeaderField: "Origin")
        request.setValue("\(Self.baseURL)/login", forHTTPHeaderField: "Referer")
        request.setValue("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36", forHTTPHeaderField: "User-Agent")
        request.httpBody = body.data(using: .utf8)

        attachCookies(to: &request)

        // Block the redirect so we can store auth cookies before following it manually
        let loginDelegate = LoginRedirectDelegate()
        let (_, loginResponse) = try await session.data(for: request, delegate: loginDelegate)

        let loginStatus = (loginResponse as? HTTPURLResponse)?.statusCode ?? -1
        for cookie in loginDelegate.capturedCookies {
            cookies.removeAll { $0.name == cookie.name }
            cookies.append(cookie)
        }
        logger.debug("Login POST → status \(loginStatus, privacy: .public), redirect cookies: \(loginDelegate.capturedCookies.map(\.name).joined(separator: ", "), privacy: .public)")

        // 302 = successful login redirect; anything else is a failed login
        guard loginStatus == 302 else {
            throw GradescopeError.loginFailed
        }

        // Verify session is established by checking the account page
        let accountData = try await get("/account")
        let html = String(data: accountData, encoding: .utf8) ?? ""
        guard html.contains("Course Dashboard") else {
            throw GradescopeError.invalidCredentials
        }

        logger.info("Gradescope login successful for \(email, privacy: .private)")
    }

    // MARK: - Courses

    /// Returns all student courses visible on the account dashboard.
    public func getCourses() async throws -> [GradescopeCourse] {
        let data = try await get("/account")
        return try parseCourses(from: data)
    }

    // MARK: - Assignments

    /// Returns all assignments for the given course ID.
    public func getAssignments(courseId: String) async throws -> [GradescopeAssignment] {
        let data = try await get("/courses/\(courseId)")
        return try parseAssignments(from: data, courseId: courseId, courseName: "")
    }

    /// Returns all assignments for a course, with the course name attached.
    public func getAssignments(for course: GradescopeCourse) async throws -> [GradescopeAssignment] {
        let data = try await get("/courses/\(course.id)")
        return try parseAssignments(from: data, courseId: course.id, courseName: course.name)
    }

    // MARK: - HTTP helpers

    private func get(_ path: String) async throws -> Data {
        var request = URLRequest(url: url(for: path))
        request.setValue("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36", forHTTPHeaderField: "User-Agent")
        attachCookies(to: &request)
        do {
            let (data, response) = try await session.data(for: request)
            storeCookies(from: response, for: request.url)
            return data
        } catch {
            throw GradescopeError.networkError(error)
        }
    }

    /// Encodes key-value pairs as application/x-www-form-urlencoded.
    /// Uses a strict allowed character set so that + and / in base64 values are encoded as %2B and %2F.
    private func formEncode(_ fields: [(String, String)]) -> String {
        // Only unreserved characters are left unencoded per RFC 3986 / HTML form spec
        var allowed = CharacterSet.alphanumerics
        allowed.insert(charactersIn: "-._*")
        return fields.map { key, value in
            let k = key.addingPercentEncoding(withAllowedCharacters: allowed) ?? key
            let v = value.addingPercentEncoding(withAllowedCharacters: allowed) ?? value
            return "\(k)=\(v)"
        }.joined(separator: "&")
    }

    private func attachCookies(to request: inout URLRequest) {
        guard !cookies.isEmpty, let url = request.url else { return }
        let applicable = cookies.filter { $0.domain.isEmpty || url.host?.hasSuffix($0.domain.trimmingCharacters(in: CharacterSet(charactersIn: "."))) == true }
        let header = applicable.map { "\($0.name)=\($0.value)" }.joined(separator: "; ")
        if !header.isEmpty {
            request.setValue(header, forHTTPHeaderField: "Cookie")
        }
    }

    private func storeCookies(from response: URLResponse, for url: URL?) {
        guard let http = response as? HTTPURLResponse,
              let url = url,
              let headerFields = http.allHeaderFields as? [String: String] else { return }
        let newCookies = HTTPCookie.cookies(withResponseHeaderFields: headerFields, for: url)
        for cookie in newCookies {
            cookies.removeAll { $0.name == cookie.name }
            cookies.append(cookie)
        }
    }

    private func url(for path: String) -> URL {
        URL(string: "\(Self.baseURL)\(path)")!
    }

    // MARK: - HTML Parsing

    private func document(from data: Data) throws -> XMLDocument {
        do {
            return try XMLDocument(data: data, options: .documentTidyHTML)
        } catch {
            throw GradescopeError.htmlParseError(error.localizedDescription)
        }
    }

    /// Extracts authenticity_token from <form action="/login"> on the home page.
    private func extractAuthenticityToken(from data: Data) throws -> String {
        let doc = try document(from: data)
        let nodes = try doc.nodes(forXPath: "//form[@action='/login']//input[@name='authenticity_token']/@value")
        guard let token = nodes.first?.stringValue, !token.isEmpty else {
            throw GradescopeError.missingElement("authenticity_token input")
        }
        return token
    }

    /// Parses the /account page for student course boxes.
    ///
    /// Mirrors Python course.py:
    ///   - Find <h1 class="pageHeading"> with text "Course Dashboard"
    ///   - Its next sibling contains <a class="courseBox"> elements
    ///   - Term/year come from preceding <li class="courseList--term"> siblings
    private func parseCourses(from data: Data) throws -> [GradescopeCourse] {
        let doc = try document(from: data)

        // XPath: all courseBox anchors inside the sibling of the Course Dashboard heading
        // Use word-boundary class match to avoid matching courseBox--shortname, courseBox--name, etc.
        let courseNodes = try doc.nodes(forXPath:
            "//h1[contains(@class,'pageHeading') and normalize-space(text())='Course Dashboard']" +
            "/following-sibling::*[1]//a[contains(concat(' ', normalize-space(@class), ' '), ' courseBox ')]"
        )

        // Tidy HTML clones <a class="courseBox"> inside each block child element it splits out.
        // Dedup by href so each course appears once (keeping the first occurrence, inside <h3>).
        var seenHrefs = Set<String>()
        let uniqueNodes = courseNodes.compactMap { node -> XMLElement? in
            guard let el = node as? XMLElement,
                  let href = el.attribute(forName: "href")?.stringValue,
                  seenHrefs.insert(href).inserted else { return nil }
            return el
        }
        logger.debug("courseBox nodes: \(courseNodes.count, privacy: .public) raw → \(uniqueNodes.count, privacy: .public) unique")

        return uniqueNodes.compactMap { element -> GradescopeCourse? in

            let href = element.attribute(forName: "href")?.stringValue ?? ""
            let id = href.split(separator: "/").last.map(String.init) ?? ""
            guard !id.isEmpty else { return nil }

            // After tidy, <a> is inside <h3 class="courseBox--shortname">, and
            // <div class="courseBox--name"> is a sibling of the <h3>, not a child of <a>.
            let shortName = element.stringValue?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""

            // Walk siblings of the parent <h3> to find courseBox--name
            var name = ""
            if let parentH3 = element.parent as? XMLElement {
                var sib = parentH3.nextSibling
                while let s = sib {
                    if let el = s as? XMLElement,
                       el.attribute(forName: "class")?.stringValue?.contains("courseBox--name") == true {
                        name = el.stringValue?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
                        break
                    }
                    sib = s.nextSibling
                }
            }

            // Term/year: walk up to courseList--coursesForTerm, then find preceding courseList--term sibling
            var term = ""
            var year = ""
            if let termText = termYearText(for: element) {
                let parts = termText.split(separator: " ")
                if parts.count >= 2 {
                    term = String(parts[0])
                    year = String(parts[1])
                }
            }

            return GradescopeCourse(id: id, name: name, shortName: shortName, term: term, year: year)
        }
    }

    /// Walks up from a courseBox <a> to the courseList--coursesForTerm ancestor,
    /// then finds the nearest preceding courseList--term sibling.
    private func termYearText(for courseBox: XMLElement) -> String? {
        // Walk up to find courseList--coursesForTerm
        var ancestor: XMLNode? = courseBox
        while let node = ancestor {
            if let el = node as? XMLElement,
               el.attribute(forName: "class")?.stringValue?.contains("courseList--coursesForTerm") == true {
                // Now walk preceding siblings to find courseList--term
                var sibling = el.previousSibling
                while let s = sibling {
                    if let termEl = s as? XMLElement,
                       termEl.attribute(forName: "class")?.stringValue?.contains("courseList--term") == true {
                        return termEl.stringValue?.trimmingCharacters(in: .whitespacesAndNewlines)
                    }
                    sibling = s.previousSibling
                }
                return nil
            }
            ancestor = node.parent
        }
        return nil
    }

    /// Parses the /courses/{id} page for the assignments table.
    ///
    /// Mirrors Python assignment.py:
    ///   - Find <table id="assignments-student-table">
    ///   - Each <tr> has: name (col 1), assignment ID (from <a> href or <button> data attr),
    ///     status (CSS class on first td), timestamps (from <time datetime="..."> elements)
    private func parseAssignments(from data: Data, courseId: String, courseName: String) throws -> [GradescopeAssignment] {
        let doc = try document(from: data)

        // Check if the table exists at all
        let tables = try doc.nodes(forXPath: "//table[@id='assignments-student-table']")
        let rows = try doc.nodes(forXPath: "//table[@id='assignments-student-table']//tbody/tr")

        return rows.compactMap { row -> GradescopeAssignment? in
            guard let rowEl = row as? XMLElement else { return nil }

            // Name cell is <th class="table--primaryLink">, status/time cells are <td>
            guard let nameCell = rowEl.elements(forName: "th").first else { return nil }
            let tdCells = rowEl.elements(forName: "td")
            let assignmentName = nameCell.stringValue?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""

            // Assignment ID: from <a href="/courses/X/assignments/Y"> or <button data-assignment-id="Y">
            var assignmentId: String? = nil
            if let anchor = firstDescendant(of: nameCell, tagName: "a"),
               let href = anchor.attribute(forName: "href")?.stringValue {
                // href is like /courses/X/assignments/Y or /courses/X/assignments/Y/submissions/Z
                let parts = href.split(separator: "/")
                if let idx = parts.firstIndex(of: "assignments"), idx + 1 < parts.count {
                    assignmentId = String(parts[idx + 1])
                }
            } else if let button = firstDescendant(of: nameCell, tagName: "button"),
                      let dataId = button.attribute(forName: "data-assignment-id")?.stringValue {
                assignmentId = dataId
            }
            guard let id = assignmentId, !id.isEmpty else { return nil }

            // Submission status: CSS class on first <td> (status cell)
            let statusCell = tdCells.first
            let statusClass = statusCell?.attribute(forName: "class")?.stringValue ?? ""
            let status: GradescopeSubmissionStatus
            if statusClass.contains("submissionStatus--score") || statusClass.contains("submissionStatus--graded") {
                status = .graded
            } else if statusClass.contains("submissionStatus--submitted") {
                status = .submitted
            } else {
                status = .unsubmitted
            }

            // Timestamps: Gradescope puts dates as plain text in <td class="hidden-column"> cells.
            // Order: released (index 2), due (index 3) among all <td>s.
            let hiddenDates = tdCells
                .filter { $0.attribute(forName: "class")?.stringValue?.contains("hidden-column") == true }
                .compactMap { $0.stringValue?.trimmingCharacters(in: .whitespacesAndNewlines) }
                .compactMap { Self.dateFormatter.date(from: $0) }

            let releasedAt = hiddenDates.count > 0 ? hiddenDates[0] : nil
            let dueAt      = hiddenDates.count > 1 ? hiddenDates[1] : nil
            let lateDueAt  = hiddenDates.count > 2 ? hiddenDates[2] : nil

            return GradescopeAssignment(
                id: id,
                courseId: courseId,
                courseName: courseName,
                name: assignmentName,
                status: status,
                releasedAt: releasedAt,
                dueAt: dueAt,
                lateDueAt: lateDueAt
            )
        }
    }

    // MARK: - XML traversal helpers

    private func firstDescendant(of element: XMLElement, tagName: String) -> XMLElement? {
        if element.name == tagName { return element }
        for child in element.children ?? [] {
            if let el = child as? XMLElement, let found = firstDescendant(of: el, tagName: tagName) {
                return found
            }
        }
        return nil
    }

    private func allDescendants(of element: XMLElement, tagName: String) -> [XMLElement] {
        var results: [XMLElement] = []
        for child in element.children ?? [] {
            if let el = child as? XMLElement {
                if el.name == tagName { results.append(el) }
                results.append(contentsOf: allDescendants(of: el, tagName: tagName))
            }
        }
        return results
    }
}
