//
//  PhotoViewModel.swift
//  Cityscape
//
//  Created by Jackson Butler on 11/9/25.
//  Rewritten during Phase C of the Firebase → Supabase migration.
//
//  Uploads raw image bytes to Supabase Storage (bucket `event-photos`),
//  then inserts a row into the `photos` table pointing at the storage URL.
//
//  Requires: a Storage bucket named `event-photos` to exist on the Supabase
//  project. Set it up in Dashboard → Storage → New bucket (mark it Public
//  so image URLs are directly loadable from the app).
//

import Foundation
import Supabase

class PhotoViewModel {
    /// Storage bucket for event photos. Kept as a constant so we only have
    /// one place to change it if we rename.
    static let bucket = "event-photos"

    /// Uploads image data for the given event, inserts a matching photo row,
    /// and returns the new photo's id (as String) or nil on failure.
    static func saveImage(eventId: UUID, data: Data, description: String = "") async -> String? {
        let client = SupabaseManager.shared
        let user = client.auth.currentUser

        // Path convention: <eventId>/<photoId>.jpg — one folder per event so
        // photos for the same event group naturally in the Storage UI.
        let photoId = UUID()
        let path = "\(eventId.uuidString)/\(photoId.uuidString).jpg"

        do {
            // 1. Upload the bytes to Supabase Storage.
            _ = try await client.storage
                .from(bucket)
                .upload(
                    path,
                    data: data,
                    options: FileOptions(contentType: "image/jpeg", upsert: false)
                )

            // 2. Get a public URL for the uploaded file (bucket must be public).
            let publicURL = try client.storage
                .from(bucket)
                .getPublicURL(path: path)

            // 3. Insert a row in the photos table referencing the URL.
            let payload = PhotoInsert(
                eventId: eventId,
                imageURL: publicURL.absoluteString,
                description: description,
                reviewerId: user?.id,
                reviewerEmail: user?.email
            )

            let inserted: Photo = try await client
                .from("photos")
                .insert(payload, returning: .representation)
                .select()
                .single()
                .execute()
                .value

            print("Photo saved: \(inserted.id?.uuidString ?? "?")")
            return inserted.id?.uuidString
        } catch {
            print("ERROR saving photo: \(error.localizedDescription)")
            return nil
        }
    }

    /// Loads all photos for a given event, newest first.
    static func fetchPhotos(for eventId: UUID) async -> [Photo] {
        do {
            let photos: [Photo] = try await SupabaseManager.shared
                .from("photos")
                .select()
                .eq("event_id", value: eventId)
                .order("posted_at", ascending: false)
                .execute()
                .value
            return photos
        } catch {
            print("ERROR fetching photos: \(error.localizedDescription)")
            return []
        }
    }
}
