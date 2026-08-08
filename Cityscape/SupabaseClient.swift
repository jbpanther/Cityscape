//
//  SupabaseClient.swift
//  Cityscape
//
//  Central Supabase client. Any Swift code that needs to talk to Supabase
//  (auth, database, storage) reaches it through `SupabaseManager.shared`.
//
//  Why a namespace + singleton?
//  - The Supabase client is safe to reuse across the whole app and holds an
//    auth session internally, so creating a fresh one per call would drop the
//    logged-in user.
//  - Using an enum-as-namespace (no cases) is Swift's idiomatic way to hold
//    a static singleton without accidentally letting anyone instantiate it.
//

import Foundation
import Supabase

enum SupabaseManager {
    static let shared: SupabaseClient = {
        guard let url = URL(string: Secrets.supabaseURL) else {
            fatalError("Invalid Supabase URL in Secrets.swift")
        }
        return SupabaseClient(
            supabaseURL: url,
            supabaseKey: Secrets.supabaseAnonKey
        )
    }()
}
