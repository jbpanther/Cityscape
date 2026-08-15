//
//  Event.swift
//  Cityscape
//
//  Created by Jackson Butler on 11/30/25.
//  Rewritten during Phase C of the Firebase → Supabase migration.
//
//  Two related types:
//    - `Event`         : full shape as read from Postgres (all DB fields present)
//    - `EventInsert`   : minimal shape sent when creating a new event — omits
//                        fields the database manages (id, timestamps, engagement
//                        counters) so Postgres can apply its defaults / triggers.
//
//  Naming: Swift stays camelCase, wire format is snake_case to match Postgres.
//  CodingKeys handle the mapping.
//

import Foundation

struct Event: Codable, Identifiable, Hashable {
    var id: UUID?
    var name: String = ""
    var description: String = ""
    var eventType: EventType?

    // Location — plain doubles. The Postgres trigger derives the PostGIS
    // `location` geography column from these automatically, so we don't
    // model it on the Swift side.
    var latitude: Double = 0.0
    var longitude: Double = 0.0

    var city: String = "nyc"                 // multi-city ready; default for MVP

    // Named startDate/endDate on the Swift side to match existing callers
    // (CustomEventView bindings, DetailView formatters).
    var startDate: Date = Date()
    var endDate: Date = Date().addingTimeInterval(86400)

    var source: String = "user"              // 'user' | 'scraped' | 'partner'

    // Engagement counters live on the row; per-user vote tracking will come later.
    var upvotes: Int = 0
    var downvotes: Int = 0
    var flagCount: Int = 0

    var createdBy: UUID?
    var createdAt: Date?
    var updatedAt: Date?

    enum CodingKeys: String, CodingKey {
        case id
        case name
        case description
        case eventType   = "event_type"
        case latitude
        case longitude
        case city
        case startDate   = "start_at"
        case endDate     = "end_at"
        case source
        case upvotes
        case downvotes
        case flagCount   = "flag_count"
        case createdBy   = "created_by"
        case createdAt   = "created_at"
        case updatedAt   = "updated_at"
    }
}


/// Payload shape for creating an event. Only fields the caller sets; the DB
/// fills in id, timestamps, defaults, and derives the geography from lat/lng.
struct EventInsert: Encodable {
    var name: String
    var description: String
    var eventType: EventType?
    var latitude: Double
    var longitude: Double
    var city: String
    var startDate: Date
    var endDate: Date
    var createdBy: UUID

    enum CodingKeys: String, CodingKey {
        case name, description, latitude, longitude, city
        case eventType  = "event_type"
        case startDate  = "start_at"
        case endDate    = "end_at"
        case createdBy  = "created_by"
    }

    init(from event: Event, userId: UUID) {
        self.name        = event.name
        self.description = event.description
        self.eventType   = event.eventType
        self.latitude    = event.latitude
        self.longitude   = event.longitude
        self.city        = event.city
        self.startDate   = event.startDate
        self.endDate     = event.endDate
        self.createdBy   = userId
    }
}


enum EventType: String, Codable, CaseIterable, Identifiable {
    case market     = "Market"
    case exhibit    = "Exhibit"
    case tour       = "Tour"
    case popup      = "Popup"
    case concert    = "Concert"
    case theatre    = "Theatre"
    case comedy     = "Comedy"
    case sports     = "Sports"
    case athletics  = "Athletics"
    case food       = "Food"
    case cultural   = "Cultural"
    case parade     = "Parade"
    case networking = "Networking"
    case other      = "Other"

    var id: String { rawValue }

    var iconName: String {
        switch self {
        case .market:     return "cart"
        case .popup:      return "sparkles"
        case .concert:    return "music.mic"
        case .theatre:    return "theatermasks"
        case .sports:     return "sportscourt"
        case .athletics:  return "figure.run"
        case .other:      return "mappin.circle"
        case .parade:     return "flag.fill"
        case .networking: return "person.3.sequence.fill"
        case .tour:       return "map"
        case .comedy:     return "face.smiling"
        case .exhibit:    return "building.columns"
        case .cultural:   return "globe.europe.africa"
        case .food:       return "fork.knife"
        }
    }
}


extension Event {
    static var preview: Event {
        Event(
            id: UUID(),
            name: "Snowport",
            description: "A winter market in the heart of Boston's Seaport District",
            eventType: .popup,
            latitude: 42.3518324925221,
            longitude: -71.044154694033,
            city: "boston",
            startDate: Date(),
            endDate: Date().addingTimeInterval(1_000_000)
        )
    }
}
