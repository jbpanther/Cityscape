//
//  Photo.swift
//  Cityscape
//
//  Created by Jackson Butler on 11/30/25.
//  Rewritten during Phase C of the Firebase → Supabase migration.
//
//  Two related types:
//    - `Photo`         : row shape as read from Postgres
//    - `PhotoInsert`   : minimal shape for creating a new photo record
//

import Foundation
import Supabase

struct Photo: Codable, Identifiable, Hashable {
    var id: UUID?
    var eventId: UUID?
    var imageURLString: String = ""
    var description: String = ""
    var reviewerId: UUID?
    var reviewerEmail: String? = SupabaseManager.shared.auth.currentUser?.email
    var postedAt: Date = Date()

    enum CodingKeys: String, CodingKey {
        case id
        case eventId       = "event_id"
        case imageURLString = "image_url"
        case description
        case reviewerId    = "reviewer_id"
        case reviewerEmail = "reviewer_email"
        case postedAt      = "posted_at"
    }
}


/// Payload shape for creating a photo row. Excludes the DB-generated id and
/// postedAt timestamp.
struct PhotoInsert: Encodable {
    var eventId: UUID
    var imageURL: String
    var description: String
    var reviewerId: UUID?
    var reviewerEmail: String?

    enum CodingKeys: String, CodingKey {
        case eventId       = "event_id"
        case imageURL      = "image_url"
        case description
        case reviewerId    = "reviewer_id"
        case reviewerEmail = "reviewer_email"
    }
}
