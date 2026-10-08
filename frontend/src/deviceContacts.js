import { Capacitor } from '@capacitor/core';
import { Contacts } from '@capacitor-community/contacts';

const collectAddresses = (contacts) => {
  const emails = [];
  const phones = [];
  (contacts || []).forEach((contact) => {
    const emailList = contact.emails || contact.email || [];
    const phoneList = contact.phones || contact.tel || [];
    emailList.forEach((email) => {
      const address = typeof email === 'string' ? email : email?.address;
      if (address) emails.push(address);
    });
    phoneList.forEach((phone) => {
      const number = typeof phone === 'string' ? phone : phone?.number;
      if (number) phones.push(number);
    });
  });
  return { emails, phones };
};

const readNativeContacts = async () => {
  const permission = await Contacts.requestPermissions();
  const state = permission?.contacts;
  if (state !== 'granted' && state !== 'limited') {
    const error = new Error('Contacts access is off. Turn it on in Settings to find friends.');
    error.code = 'denied';
    throw error;
  }
  const { contacts } = await Contacts.getContacts({
    projection: { emails: true, phones: true },
  });
  return collectAddresses(contacts);
};

const readBrowserContacts = async () => {
  if (!navigator.contacts?.select) {
    const error = new Error('Finding friends from contacts works in the SunCast app on your phone.');
    error.code = 'unavailable';
    throw error;
  }
  let contacts;
  try {
    contacts = await navigator.contacts.select(['email', 'tel'], { multiple: true });
  } catch (err) {
    if (err?.name === 'AbortError' || err?.name === 'InvalidStateError') {
      const cancel = new Error('cancelled');
      cancel.code = 'cancelled';
      throw cancel;
    }
    const error = new Error('Finding friends from contacts works in the SunCast app on your phone.');
    error.code = 'unavailable';
    throw error;
  }
  return collectAddresses(contacts);
};

/** Ask for contacts and return only email addresses and phone numbers. */
export async function readContactAddresses() {
  if (Capacitor.isNativePlatform()) return readNativeContacts();
  return readBrowserContacts();
}
