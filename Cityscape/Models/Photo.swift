//
//  Photo.swift
//  Cityscape
//
//  Created by Jackson Butler on 11/30/25.
//

import Foundation
import FirebaseFirestore
import Supabase

class Photo: Identifiable, Codable, Equatable, Hashable {
    @DocumentID var id: String?
    var imageURLString = "" //this will hold the URL string
    var description = ""
    // Auth moved to Supabase in Phase B — pull the reviewer email from the
    // Supabase session instead of Firebase's currentUser.
    var reviewer: String = SupabaseManager.shared.auth.currentUser?.email ?? ""
    var postedOn: Date = Date()

    init(
        id: String? = nil,
        imageURLString: String = "",
        description: String = "",
        reviewer: String = SupabaseManager.shared.auth.currentUser?.email ?? "",
        postedOn: Date = Date()
    ) {
        self.id = id
        self.imageURLString = imageURLString
        self.description = description
        self.reviewer = reviewer
        self.postedOn = postedOn
    }

    static func == (lhs: Photo, rhs: Photo) -> Bool {
        return lhs.id == rhs.id &&
               lhs.imageURLString == rhs.imageURLString &&
               lhs.description == rhs.description &&
               lhs.reviewer == rhs.reviewer &&
               lhs.postedOn == rhs.postedOn
    }

    func hash(into hasher: inout Hasher) {
        hasher.combine(id)
        hasher.combine(imageURLString)
        hasher.combine(description)
        hasher.combine(reviewer)
        hasher.combine(postedOn)
    }
}
